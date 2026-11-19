import json
from unittest.mock import patch

import pytest

from app.infrastructure.ai.components import invoke_json_component
from app.infrastructure.persistence.models import Guardian, User, uid
from app.infrastructure.security.experience_tokens import seal, unseal
from app.infrastructure.security.tokens import create_access_token

BASE = "/guardian/experience"
FLOW = "app.application.workflows.guardian_experience"


@pytest.fixture
def adult(db):
    identifier = uid()
    db.add(User(id=identifier, type="guardian"))
    db.flush()
    db.add(Guardian(id=identifier, name="Parent", email="parent@example.com", role="guardian"))
    db.commit()
    return identifier, {"Authorization": f"Bearer {create_access_token(user_id=identifier, role='guardian')}"}


@pytest.fixture
def model():
    with patch(f"{FLOW}.QwenTutorTurnGateway") as gateway, patch(f"{FLOW}.QwenLeakJudge") as judge:
        gateway.return_value.complete.return_value = {
            "act": "guide", "content": "先想想怎样把分母变成相同的数？",
            "turn": {"type": "work", "relation": "new", "depth": "reasoning"},
        }
        judge.return_value.check_math.return_value = True
        judge.return_value.leaks.return_value = {"leaks": False, "answer_protected": True, "reason": None}
        judge.return_value.visual_leaks.return_value = False
        yield gateway.return_value, judge.return_value


def test_adult_without_children_uses_checked_tutoring_without_any_business_writes(client, db, adult, model):
    from app.infrastructure.persistence.database import Base
    before = {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables}
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较3/4与2/3，给我提示"})
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "先想想怎样把分母变成相同的数？"
    state = unseal(response.json()["state_token"], adult[0], "conversation")
    assert state["problem"]["disclosure"] == "protected"
    assert state["problem"]["hints_given"] == 1
    assert len(state["window"]) == 2
    assert {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables} == before


def test_multi_turn_keeps_protection_and_only_the_signed_adult_window(client, adult, model):
    first = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较3/4与2/3"}).json()
    model[0].complete.return_value["turn"]["relation"] = "same"
    second = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "我不知道怎么通分", "state_token": first["state_token"]})
    assert second.status_code == 200, second.text
    call = model[0].complete.call_args.kwargs
    assert json.loads(call["instruction"])["permit"]["answer_protected"] is True
    assert call["envelope"]["actor"] == {"role": "guardian", "experience": True}
    assert call["envelope"]["memory"] == []
    assert any(row["text"] == "比较3/4与2/3" for row in call["recent_utterances"])


@pytest.mark.parametrize("body", [{}, {"content": " "}, {"content": "hi", "ward_id": "child"},
                                  {"content": "hi", "history": []}])
def test_rejects_empty_input_and_client_injected_ward_or_history(client, adult, body):
    assert client.post(f"{BASE}/turn", headers=adult[1], json=body).status_code == 422


def test_tokens_are_account_purpose_expiry_and_signature_bound(client, adult):
    for token in [seal("other", "conversation", {}), seal(adult[0], "speech", {}),
                  seal(adult[0], "conversation", {}) + "x", "not-a-token"]:
        assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "hi", "state_token": token}).status_code == 409
    with patch("app.infrastructure.security.experience_tokens.time.time", return_value=0):
        token = seal(adult[0], "conversation", {})
    assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "hi", "state_token": token}).status_code == 409


def test_all_experience_endpoints_require_adult_auth(client, adult):
    for path, body in [("turn", {"content": "hi"}), ("attachments/upload-url", {"extension": "jpg", "content_type": "image/jpeg"}),
                       ("speech", {"speech_ref": "x"})]:
        assert client.post(f"{BASE}/{path}", json=body).status_code == 401
        headers = {"Authorization": f"Bearer {create_access_token(user_id=adult[0], role='ward')}"}
        assert client.post(f"{BASE}/{path}", headers=headers, json=body).status_code == 401


@pytest.mark.parametrize("key", ["ward/child/companion/a.jpg", "guardian/other/experience/a.jpg", "../a.jpg"])
def test_images_cannot_cross_guardians_or_read_child_media(client, adult, key):
    assert client.post(f"{BASE}/turn", headers=adult[1], json={"attachment_keys": [key]}).status_code == 400


def test_uploaded_images_use_guardian_namespace_and_reject_mime_mismatch(client, adult):
    with patch("app.api.v1.guardian_experience.storage.upload_url", return_value=("https://upload", 9999999999, {})):
        result = client.post(f"{BASE}/attachments/upload-url", headers=adult[1], json={"extension": "png", "content_type": "image/png"})
    assert result.status_code == 200
    assert result.json()["oss_key"].startswith(f"guardian/{adult[0]}/experience/")
    assert client.post(f"{BASE}/attachments/upload-url", headers=adult[1], json={"extension": "jpg", "content_type": "image/png"}).status_code == 400


def test_approved_image_reaches_model_and_independent_judge(client, adult, model):
    from app.application.workflows.tutor_loop import ModelCall, TurnResult, Vetting
    from app.application.workflows.tutor_turn import TutorTurnCandidate
    candidate = TutorTurnCandidate.model_validate(model[0].complete.return_value)
    result = TurnResult(ModelCall(candidate), Vetting(candidate, None))
    key = f"guardian/{adult[0]}/experience/a.png"
    with patch("app.api.v1.guardian_experience.storage.exists", return_value=True), patch(f"{FLOW}.storage.read_bytes", return_value=b"image"), patch(f"{FLOW}.run_tutor_turn", return_value=result) as run:
        result = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "请给一个提示", "attachment_keys": [key]})
    assert result.status_code == 200, result.text
    assert run.call_args.args[4][0].startswith("data:image/png;base64,")
    assert run.call_args.kwargs["judge_images"] == run.call_args.args[4]


def test_judge_failure_never_shows_rejected_draft_or_advances_problem(client, adult, model):
    model[1].leaks.return_value = None
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较分数"})
    assert response.status_code == 200
    assert response.json()["act"] == "unavailable"
    assert "先想想" not in response.json()["content"]
    assert unseal(response.json()["state_token"], adult[0], "conversation")["problem"] is None


def test_checked_diagram_is_returned_and_pronunciation_has_its_own_scoped_token(client, adult, model):
    diagram = {"kind": "steps", "alt": "比较分数的两个步骤", "steps": [{"label": "通分"}, {"label": "比较"}]}
    model[0].complete.return_value["visual"] = diagram
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "怎么比较两个分数？"})
    assert response.status_code == 200, response.text
    assert response.json()["visual"]["steps"][0]["label"] == "通分"
    model[0].complete.return_value = {
        "act": "pronounce", "content": "听听这个词怎么读。", "pronounce": {"lesson": {
            "source_text": "apple", "locale": "en-US", "introduction": "读一读", "reading_guide": "注意第一个音节。",
        }},
    }
    response = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "apple怎么读？"})
    assert response.status_code == 200, response.text
    lesson = response.json()["lessons"][0]
    assert unseal(lesson["speech_ref"], adult[0], "speech")["source_text"] == "apple"
    with pytest.raises(ValueError):
        unseal(lesson["speech_ref"], adult[0], "conversation")


def test_speech_only_uses_server_approved_lesson_and_supported_rate(client, adult):
    ref = seal(adult[0], "speech", {"source_text": "apple", "locale": "en-US"})
    with patch("app.api.v1.guardian_experience.AliyunSpeechSynthesizer") as synth:
        synth.return_value.synthesize.return_value = b"mp3"
        result = client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "rate": 0.75})
        assert result.content == b"mp3"
        synth.return_value.synthesize.assert_called_once_with(text="apple", locale="en-US", rate=0.75)
    assert client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "rate": 2}).status_code == 400
    assert client.post(f"{BASE}/speech", headers=adult[1], json={"speech_ref": ref, "source_text": "injected"}).status_code == 422


def test_guardian_explain_mode_reuses_problem_solving_with_zero_db_writes_and_isolated_token(client, db, adult):
    from app.infrastructure.persistence.database import Base

    MENTOR_FLOW = "app.application.workflows.guardian_mentor"
    good_t1 = {
        "subject": "math",
        "final_answers": {"main": "2"},
        "scoring_points": [{"id": "SP1", "step": "求导得 2x-4=0", "points": 2}],
        "implicit_constraints": [],
        "approaches": [
            {
                "id": "A1",
                "name": "求导法",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求一阶导数",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "2*x - 4",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2 - 4*x", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }
    mentor_reply = {
        "act": "explain",
        "content": "### 考点与题眼\n二次函数对称轴与极值点。\n\n### 完整破题思路与解答\n求导得 $f'(x)=2x-4$，令其为 0 得 $x=2$。\n\n### 孩子常见卡点与启发建议\n容易漏看负号，可追问一次项系数符号。",
        "visual": {
            "kind": "segment",
            "alt": "对称轴示意",
            "bars": [{"label": "坐标轴", "segments": [{"label": "对称轴位置", "value": 2, "unknown": False}]}],
        },
    }
    before = {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables}
    with patch(f"{MENTOR_FLOW}.QwenProblemSolverGateway") as solver_cls, patch(
        f"{MENTOR_FLOW}.QwenMentorExplainGateway"
    ) as mentor_cls:
        solver_cls.return_value.extract_stem.return_value = {
            "subject": "math",
            "raw_text": "求 f(x)=x**2-4*x 的对称轴",
            "subproblems": [],
        }
        solver_cls.return_value.solve_route.return_value = good_t1
        mentor_cls.return_value.review.return_value = True
        mentor_cls.return_value.explain.return_value = mentor_reply

        res = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "求 f(x)=x**2-4*x 的对称轴", "mode": "guardian_explain"},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "guardian_explain"
    assert body["act"] == "explain"
    assert "x=2" in body["content"]
    assert body["visual"]["bars"][0]["segments"][0]["value"] == 2
    review = mentor_cls.return_value.review.call_args.kwargs
    assert review["candidate"].content == mentor_reply["content"]
    assert review["solution"].mentor_projection()["verified_final_answers"] == {}
    assert body["verification"]["draft_reviewed"] is True
    assert body["verification"]["status"] == "ready"
    assert body["verification"]["confidence"] in {"medium", "high"}

    # Zero writes to any business/student table
    assert {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables} == before

    # Token is strictly scoped to conversation_mentor; mixing across modes returns 409
    mentor_token = body["state_token"]
    state = unseal(mentor_token, adult[0], "conversation_mentor")
    assert len(state["window"]) == 2
    assert (
        client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "继续问", "mode": "student_guide", "state_token": mentor_token},
        ).status_code
        == 409
    )
    student_token = seal(adult[0], "conversation", {"window": []})
    assert (
        client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "看完整解析", "mode": "guardian_explain", "state_token": student_token},
        ).status_code
        == 409
    )


def test_guardian_explain_enforces_confidence_honesty_gate_and_never_reads_ward_dossiers(client, db, adult):
    from app.application.ports.problem_solving import SqlProblemDossierRepository
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
        StructuredStem,
    )
    from app.infrastructure.persistence.models import Ward, now

    MENTOR_FLOW = "app.application.workflows.guardian_mentor"
    # Seed a ward-scoped dossier with identical stem — guardian_explain MUST NOT read it!
    w_user = User(id=uid(), type="ward")
    db.add(w_user)
    db.flush()
    ward = Ward(id=w_user.id, display_name="测试学生", grade_stage="middle_school")
    db.add(ward)
    db.flush()
    stem = StructuredStem(subject="math", raw_text="模糊图题 f(x)=ax^2")
    ward_private = ProblemDossier.create_pending(
        dossier_id=uid(), scope="ward", owner_ward_id=ward.id, stem=stem, tier="T2", solver_version="v1", now_at=now()
    ).complete_solve(
        approaches=(), invariants=(), scoring_points=(), final_answers={"main": "PRIVATE_WARD_SECRET"},
        confidence="high", tier="T2", evidence={},
    )
    SqlProblemDossierRepository(db).save(ward_private)
    db.commit()

    key = f"guardian/{adult[0]}/experience/blurry.png"
    disputed_route_a = {
        "subject": "math",
        "uncertain": True,
        "final_answers": {"main": "1"},
        "approaches": [{"id": "A1", "name": "路线1", "milestones": [{"id": "M1", "goal": "步骤1", "check_kind": "conceptual_rubric"}]}],
    }
    disputed_route_b = {
        "subject": "math",
        "final_answers": {"main": "2"},
        "approaches": [{"id": "A1", "name": "路线2", "milestones": [{"id": "M1", "goal": "步骤1", "check_kind": "conceptual_rubric"}]}],
    }
    with (
        patch("app.api.v1.guardian_experience.storage.exists", return_value=True),
        patch(f"{FLOW}.storage.read_bytes", return_value=b"pngbytes"),
        patch(f"{MENTOR_FLOW}.QwenProblemSolverGateway") as solver_cls,
        patch(f"{MENTOR_FLOW}.QwenMentorExplainGateway") as mentor_cls,
    ):
        solver_cls.return_value.extract_stem.side_effect = [
            {"subject": "math", "raw_text": "模糊图题 f(x)=ax^2", "subproblems": [], "needs_student_confirmation": True},
            {"subject": "math", "raw_text": "模糊图题 f(x)=ax^3", "subproblems": []},  # reread mismatch!
        ]
        solver_cls.return_value.solve_route.side_effect = [
            disputed_route_a,
            disputed_route_a,
            disputed_route_b,
        ]
        mentor_cls.return_value.review.return_value = True
        mentor_cls.return_value.explain.return_value = {
            "act": "explain",
            "content": "按当前识别条件推导思路如下……",
            "visual": {"kind": "unknown_illegal_kind", "alt": "坏图"},  # bad visual is dropped cleanly
        }
        res = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "模糊图题 f(x)=ax^2", "attachment_keys": [key], "mode": "guardian_explain"},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    # Ward private dossier was NOT used
    passed_solution = mentor_cls.return_value.explain.call_args.kwargs["verified_solution"]
    assert "PRIVATE_WARD_SECRET" not in json.dumps(passed_solution.mentor_projection())
    # Confidence honesty gate surfaced low confidence + condition confirmation prefix, and dropped invalid visual
    assert body["verification"]["confidence"] == "low"
    assert body["verification"]["needs_condition_confirmation"] is True
    assert "题面核对提示" in body["content"]
    assert "visual" not in body


def test_guardian_explain_safety_and_rate_limit_and_no_student_permit_backdoor(client, adult):
    import inspect

    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy

    # Invariant: Student protection code has zero bypass parameters
    assert list(inspect.signature(TutorPermitPolicy.permit).parameters) == ["problem"]
    assert "bypass" not in inspect.signature(run_tutor_turn).parameters
    assert "allow_answer" not in inspect.signature(run_tutor_turn).parameters

    # Safety screening still blocks unsafe adult input
    unsafe = client.post(
        f"{BASE}/turn",
        headers=adult[1],
        json={"content": "我想自杀伤害自己", "mode": "guardian_explain"},
    )
    assert unsafe.status_code == 200
    assert unsafe.json()["act"] == "safety"

    # Rate limit protects against automated homework scraping
    from app.application.workflows.guardian_mentor import mentor_rate_limiter

    mentor_rate_limiter.reset()
    try:
        with (
            patch.object(mentor_rate_limiter, "per_minute", 2),
            patch("app.application.workflows.guardian_mentor.QwenProblemSolverGateway") as s_cls,
            patch("app.application.workflows.guardian_mentor.QwenMentorExplainGateway") as m_cls,
        ):
            s_cls.return_value.extract_stem.return_value = None
            s_cls.return_value.solve_route.return_value = None
            m_cls.return_value.explain.return_value = {"act": "answer", "content": "概念解释。"}
            assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "问题1", "mode": "guardian_explain"}).status_code == 200
            assert client.post(f"{BASE}/turn", headers=adult[1], json={"content": "问题2", "mode": "guardian_explain"}).status_code == 200
            limited = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "问题3", "mode": "guardian_explain"})
            assert limited.status_code == 429
            assert limited.json()["detail"]["code"] == "mentor_rate_limited"
    finally:
        mentor_rate_limiter.reset()


def test_guardian_explain_reuses_ready_bank_dossier_without_rerunning_solver_routes(client, db, adult):
    from app.application.ports.problem_solving import SqlProblemDossierRepository
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
        StructuredStem,
    )
    from app.contexts.tutoring.domain.blueprint import Approach, Milestone
    from app.infrastructure.persistence.models import now

    MENTOR_FLOW = "app.application.workflows.guardian_mentor"
    stem = StructuredStem(subject="math", raw_text="已知题库真题求极值")
    bank_dossier = ProblemDossier.create_pending(
        dossier_id=uid(), scope="bank", owner_ward_id=None, stem=stem, tier="T2", solver_version="v1", now_at=now()
    ).complete_solve(
        approaches=(
            Approach(
                id="A1",
                name="官方解析路线",
                milestones=(Milestone(id="M1", goal="求导", verification_status="verified"),),
            ),
        ),
        invariants=(),
        scoring_points=(),
        final_answers={"main": "42"},
        confidence="high",
        tier="T2",
        evidence={"bank_matched": True},
    )
    SqlProblemDossierRepository(db).save(bank_dossier)
    db.commit()

    with patch(f"{MENTOR_FLOW}.QwenProblemSolverGateway") as solver_cls, patch(
        f"{MENTOR_FLOW}.QwenMentorExplainGateway"
    ) as mentor_cls:
        solver_cls.return_value.extract_stem.return_value = {
            "subject": "math",
            "raw_text": "已知题库真题求极值",
            "subproblems": [],
        }
        mentor_cls.return_value.review.return_value = True
        mentor_cls.return_value.explain.return_value = {
            "act": "explain",
            "content": "### 完整破题思路与解答\n最终结果为 42。",
        }
        res = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "已知题库真题求极值", "mode": "guardian_explain"},
        )

    assert res.status_code == 200, res.text
    assert solver_cls.return_value.solve_route.call_count == 0
    assert res.json()["verification"]["confidence"] == "high"


def test_qwen_mentor_explain_gateway_supports_both_legacy_snapshot_and_upgraded_component():
    from pathlib import Path
    from types import SimpleNamespace

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.definitions import use_definitions
    from app.application.workflows.guardian_mentor import QwenMentorExplainGateway
    from app.infrastructure.ai.components import ChatCompletionResult
    from scripts.upgrade_math_bundle import upgrade

    raw_release = json.loads(Path("tests/fixtures/admin-release.json").read_text(encoding="utf-8"))
    fake_settings = SimpleNamespace(agent_model_enabled=True, dashscope_api_key="sk-test", agent_model_timeout_seconds=30)

    # 1. Legacy release without `tutoring.mentor-explain` falls back cleanly through `components.complete_json_chat`
    legacy_compiled = compile_bundle(raw_release["bundle"])
    with use_definitions(legacy_compiled.catalog), patch(
        "app.infrastructure.ai.components.complete_json_chat",
        return_value=ChatCompletionResult(
            raw='{"act":"explain","content":"旧快照兼容解析正文"}',
            raw_wire='{"act":"explain","content":"旧快照兼容解析正文"}',
            finish_reason="stop",
            stream_completed=True,
        ),
    ) as chat_mock:
        out = QwenMentorExplainGateway(settings_obj=fake_settings).explain(
            content="测试题目",
            verified_solution=None,
            recent_utterances=[],
            current_images=[],
        )
        assert out["act"] == "explain"
        assert out["content"] == "旧快照兼容解析正文"
        assert chat_mock.call_count == 1

    # 2. Upgraded release with `tutoring.mentor-explain` invokes the dedicated registered Agent component
    upgraded = upgrade(raw_release, guardian_mentor=True)
    upgraded_compiled = compile_bundle(upgraded["bundle"])
    with use_definitions(upgraded_compiled.catalog), patch(
        "app.infrastructure.ai.components.invoke_agent_component"
    ) as invoke_mock:
        invoke_mock.return_value.unwrap.return_value = {"act": "explain", "content": "专属组件解析正文"}
        out2 = QwenMentorExplainGateway(settings_obj=fake_settings).explain(
            content="测试题目",
            verified_solution=None,
            recent_utterances=[],
            current_images=[],
        )
        assert out2["content"] == "专属组件解析正文"
        assert invoke_mock.call_args.kwargs["spec"].component_id == "tutoring.mentor-explain"


def test_mentor_handoff_keeps_original_and_followup(client, adult, model):
    first = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "比较3/4与2/3"}).json()
    model[0].complete.return_value["turn"]["relation"] = "same"
    second = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "我觉得是6", "state_token": first["state_token"]}).json()
    handoff = unseal(second["mentor_start_token"], adult[0], "conversation_mentor")
    assert handoff["origin"]["text"] == "比较3/4与2/3"
    assert any(row["text"] == "我觉得是6" for row in handoff["window"])


def test_real_stem_gateway_preserves_fast_path_classification():
    from app.application.ports.problem_solving import QwenProblemSolverGateway

    gateway = QwenProblemSolverGateway()
    with patch.object(gateway, "_invoke", return_value={"tier": "T0", "subject": "english", "raw_text": "apple怎么读"}):
        from app.application.workflows.guardian_mentor import _solve_for_mentor

        assert gateway.extract_stem(text="apple怎么读", images=[])["tier"] == "T0"
        # Use the actual extraction adapter, with the provider transport replaced.
        from types import SimpleNamespace

        from app.agent_specs.gaokao_contracts import PLANNER_ID

        with (patch("app.agent_specs.definitions.load_definitions", return_value=SimpleNamespace(units={PLANNER_ID: {}})),
              patch.object(gateway, "solve_route") as route):
            result = _solve_for_mentor(content="apple怎么读", images=[], solver=gateway, bank_lookup=None)
        assert result.tier == "T0"
        route.assert_not_called()


def test_solver_runs_after_auth_and_lookup_checkout_released(client, db, adult):
    flow = "app.application.workflows.guardian_mentor"
    transactions = []
    def extract(**kw):
        transactions.append(db.in_transaction())
        return {"raw_text": "2+3", "subject": "math"}
    def solve(**kw):
        transactions.append(db.in_transaction())
    with patch(f"{flow}.QwenProblemSolverGateway") as solver, patch(f"{flow}.QwenMentorExplainGateway") as mentor:
        solver.return_value.extract_stem.side_effect = extract
        solver.return_value.solve_route.side_effect = solve
        mentor.return_value.explain.return_value = {"act": "clarify", "content": "请补充题目"}
        client.post(f"{BASE}/turn", headers=adult[1], json={"content": "2+3", "mode": "guardian_explain"})
    assert transactions and not any(transactions)


def test_failed_final_review_hides_contradictory_mentor_answer(client, adult):
    flow = "app.application.workflows.guardian_mentor"
    with patch(f"{flow}.QwenProblemSolverGateway") as solver, patch(f"{flow}.QwenMentorExplainGateway") as mentor:
        solver.return_value.extract_stem.return_value = {"subject": "math", "raw_text": "3×4"}
        solver.return_value.solve_route.return_value = None
        mentor.return_value.explain.return_value = {"act": "answer", "content": "3×4=21"}
        mentor.return_value.review.return_value = False
        result = client.post(f"{BASE}/turn", headers=adult[1], json={"content": "求3×4", "mode": "guardian_explain"}).json()
    assert result["act"] == "unavailable"
    assert "21" not in result["content"]


def test_mentor_photo_followup_reaches_solver_with_original_and_current_request(client, adult, model):
    flow = "app.application.workflows.guardian_mentor"
    from app.application.workflows.tutor_loop import ModelCall, TurnResult, Vetting
    from app.application.workflows.tutor_turn import TutorTurnCandidate

    def accepted_turn(*args, **kwargs):
        candidate = TutorTurnCandidate.model_validate(model[0].complete.return_value)
        return TurnResult(ModelCall(candidate), Vetting(candidate, None))

    key = f"guardian/{adult[0]}/experience/problem.png"
    with (patch(f"{FLOW}.run_tutor_turn", side_effect=accepted_turn),
          patch("app.api.v1.guardian_experience.storage.exists", return_value=True),
          patch(f"{FLOW}.storage.read_bytes", return_value=b"original picture"),
          patch("app.application.workflows.image_target.select_history_images",
                return_value={"target_image_ids": [1], "ambiguous": False}),
          patch(f"{flow}.QwenProblemSolverGateway") as solver,
          patch(f"{flow}.QwenMentorExplainGateway") as mentor):
        first = client.post(f"{BASE}/turn", headers=adult[1], json={
            "content": "比较图中两个分数", "attachment_keys": [key],
        }).json()
        # The student model may label a new attempt on the selected old photo as new.
        model[0].complete.return_value["turn"]["relation"] = "new"
        second = client.post(f"{BASE}/turn", headers=adult[1], json={
            "content": "我觉得是6", "state_token": first["state_token"],
        }).json()
        solver.return_value.extract_stem.return_value = {"raw_text": "比较图中两个分数", "tier": "T1"}
        solver.return_value.solve_route.return_value = None
        mentor.return_value.explain.return_value = {"act": "explain", "content": "题图中需要先通分。"}
        mentor.return_value.review.return_value = True
        result = client.post(f"{BASE}/turn", headers=adult[1], json={
            "content": "我觉得是6", "mode": "guardian_explain", "state_token": second["mentor_start_token"],
        }).json()
        assert result["act"] == "explain"
        call = solver.return_value.extract_stem.call_args_list[0].kwargs
        assert "比较图中两个分数" in call["text"] and "我觉得是6" in call["text"]
        assert len(call["images"]) == 1
        assert "完整解析" in mentor.return_value.explain.call_args.kwargs["content"]
        solver.reset_mock()
        result = client.post(f"{BASE}/turn", headers=adult[1], json={
            "content": "为什么这里要通分", "mode": "guardian_explain", "state_token": result["state_token"],
        }).json()
        call = solver.return_value.extract_stem.call_args_list[0].kwargs
        assert "比较图中两个分数" in call["text"] and "为什么这里要通分" in call["text"]
        assert len(call["images"]) == 1


def test_mentor_model_timeouts_share_one_budget_without_changing_other_calls():
    from app.infrastructure.ai.client import model_time_budget, remaining_model_time

    with patch("app.infrastructure.ai.client.monotonic", side_effect=[100, 112, 121]), model_time_budget(20):
        assert remaining_model_time() == 8
        with pytest.raises(TimeoutError):
            remaining_model_time()
    assert remaining_model_time() is None


@pytest.mark.parametrize(("wire", "accepted"), [
    ('{"consistent":true}', True), ('{"consistent":false}', False), ('{"consistent":"true"}', False),
])
def test_final_review_uses_actual_draft_and_strict_verdict(wire, accepted):
    from types import SimpleNamespace

    from app.application.workflows.guardian_mentor import (
        MentorExplainCandidate,
        QwenMentorExplainGateway,
    )
    from app.infrastructure.ai.components import ChatCompletionResult

    gateway = QwenMentorExplainGateway(SimpleNamespace(agent_model_enabled=True, dashscope_api_key="test"))
    with patch("app.infrastructure.ai.components.complete_json_chat", return_value=ChatCompletionResult(
        raw=wire, raw_wire=wire, finish_reason="stop", stream_completed=True,
    )) as chat:
        result = gateway.review(
            question="3×4",
            solution=None,
            candidate=MentorExplainCandidate(act="explain", content="答案是21"),
            images=[],
        )
    assert result is accepted
    messages = chat.call_args.kwargs["messages"]
    # DashScope requires an explicit JSON instruction for json_object mode.
    assert "json" in messages[0]["content"].lower()
    payload = json.loads(messages[1]["content"][0]["text"])
    assert payload["draft"] == "答案是21" and payload["question"] == "3×4"


@pytest.mark.parametrize("act", ["answer", "explain"])
def test_legacy_mentor_review_and_notice_are_independent(client, adult, act):
    flow = "app.application.workflows.guardian_mentor"
    with (
        patch(f"{flow}._solve_for_mentor", return_value=None),
        patch(f"{flow}.QwenMentorExplainGateway") as mentor,
    ):
        mentor.return_value.explain.return_value = {
            "act": act,
            "content": "比喻把一种事物比作另一种。",
        }
        mentor.return_value.review.return_value = True
        result = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={
                "content": "什么是比喻",
                "mode": "guardian_explain",
            },
        ).json()
    mentor.return_value.review.assert_called_once()
    assert ("核验状态说明" in result["content"]) == (act == "explain")


def test_mentor_new_photo_retires_expired_first_topic(client, adult):
    flow = "app.application.workflows.guardian_mentor"
    first, second = [
        f"guardian/{adult[0]}/experience/{name}.png" for name in ("A", "B")
    ]
    old = {
        "turn_id": "A",
        "author": "ward",
        "text": "第一题",
        "attachment_refs": [first],
    }
    state = seal(adult[0], "conversation_mentor", {"origin": old, "window": []})
    with (
        patch(f"{FLOW}.storage.read_bytes", return_value=b"image"),
        patch("app.api.v1.guardian_experience.storage.exists", return_value=True),
        patch(f"{flow}._solve_for_mentor", return_value=None),
        patch(f"{flow}.QwenMentorExplainGateway") as mentor,
    ):
        mentor.return_value.explain.return_value = {
            "act": "answer",
            "content": "第二题讲解",
        }
        mentor.return_value.review.return_value = True
        result = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={
                "content": "第二题",
                "mode": "guardian_explain",
                "state_token": state,
                "attachment_keys": [second],
            },
        ).json()
        assert not mentor.return_value.explain.call_args.kwargs["recent_utterances"]
        state = unseal(result["state_token"], adult[0], "conversation_mentor")
        assert first not in json.dumps(state)


def test_review_records_metadata_without_draft(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.application.workflows.guardian_mentor import (
        MentorExplainCandidate,
        QwenMentorExplainGateway,
    )
    from app.infrastructure.ai.components import ChatCompletionResult, capture_llm_calls

    target = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(target))
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "1")
    gateway = QwenMentorExplainGateway(
        SimpleNamespace(agent_model_enabled=True, dashscope_api_key="test")
    )
    with (
        capture_llm_calls() as calls,
        patch(
            "app.infrastructure.ai.components.complete_json_chat",
            return_value=ChatCompletionResult(
                raw='{"consistent":false}',
                finish_reason="stop",
                stream_completed=True,
                tokens_in=42,
                tokens_out=5,
            ),
        ),
    ):
        assert not gateway.review(
            question="private-stem",
            solution=None,
            candidate=MentorExplainCandidate(act="answer", content="private-draft"),
            images=[],
        )
    assert calls[-1]["outcome"] == "review_rejected"
    metadata = json.loads(target.read_text().splitlines()[-1])["metadata"]
    assert metadata["llm.tokens_in"] == 42 and metadata["llm.finish_reason"] == "stop"
    assert metadata["llm.duration_ms"] >= 0 and "private-" not in target.read_text()


@pytest.mark.parametrize("upgraded", [False, True])
@pytest.mark.parametrize("budget_expired", [False, True])
def test_only_turn_deadline_maps_to_503_for_both_snapshots(
    client, adult, upgraded, budget_expired, monkeypatch
):
    from pathlib import Path
    from types import SimpleNamespace

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.definitions import use_definitions
    from app.application.workflows.guardian_mentor import QwenMentorExplainGateway
    from app.infrastructure.ai import components
    from app.infrastructure.ai.client import remaining_model_time
    from scripts.upgrade_math_bundle import upgrade

    raw = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    bundle = upgrade(raw, guardian_mentor=True)["bundle"] if upgraded else raw["bundle"]
    ticks = [0.0]

    def slow_call(**kwargs):
        if budget_expired:
            ticks[0] = 106.0
            remaining_model_time()
        raise TimeoutError("single provider call timed out")

    monkeypatch.setattr("app.infrastructure.ai.client.monotonic", lambda: ticks[0])
    gateway = QwenMentorExplainGateway(
        SimpleNamespace(
            agent_model_enabled=True,
            dashscope_api_key="test",
            agent_model_timeout_seconds=30,
        )
    )
    with (
        use_definitions(compile_bundle(bundle).catalog),
        patch(
            "app.application.workflows.guardian_mentor._solve_for_mentor",
            return_value=None,
        ),
        patch(
            "app.application.workflows.guardian_mentor.QwenMentorExplainGateway",
            return_value=gateway,
        ),
        patch("app.infrastructure.ai.client.dashscope_client"),
        patch.object(components, "invoke_json_component", invoke_json_component),
        patch.object(components, "complete_json_chat", side_effect=slow_call),
    ):
        result = client.post(
            f"{BASE}/turn",
            headers=adult[1],
            json={"content": "解释比喻", "mode": "guardian_explain"},
        )
    if budget_expired:
        assert (
            result.status_code == 503
            and result.json()["detail"]["code"] == "mentor_timeout"
        )
    else:
        assert result.status_code == 200 and result.json()["act"] == "unavailable"


def test_mentor_text_topic_switch_and_long_followups(client, adult):
    flow = "app.application.workflows.guardian_mentor"
    with patch(f"{flow}._solve_for_mentor", return_value=None), patch(f"{flow}.QwenMentorExplainGateway") as mentor:
        gateway = mentor.return_value
        gateway.review.return_value = True
        token = None
        for question, relation in [("第一道题", "new"), ("第二道题", "new"), *[("继续解释这一步", "same")] * 5]:
            gateway.explain.return_value = {"act": "answer", "content": "解释。", "topic_relation": relation}
            response = client.post(f"{BASE}/turn", headers=adult[1], json={
                "mode": "guardian_explain", "state_token": token, "content": question,
            })
            assert response.status_code == 200
            token = response.json()["state_token"]
        state = unseal(token, adult[0], "conversation_mentor")
        assert state["origin"]["text"] == "第二道题"
        assert all(row["text"] != "第二道题" for row in state["window"])
        assert "第一道题" not in gateway.review.call_args.kwargs["question"]
        assert "第二道题" in gateway.review.call_args.kwargs["question"]


def test_standard_mentor_problem_does_not_repeat_solver_after_unverified_anchors():
    from app.application.workflows.guardian_mentor import _solve_for_mentor

    with patch("app.application.workflows.guardian_mentor.solve_and_verify_problem") as solve:
        from unittest.mock import Mock

        solver = Mock()
        solver.extract_stem.return_value = {"tier": "T1", "raw_text": "比较3/4和2/3"}
        _solve_for_mentor(content="比较3/4和2/3", images=[], solver=solver, bank_lookup=None)
    assert solve.call_args.kwargs["initial_tier"] == "T1"
    assert solve.call_args.kwargs["allow_t2_escalation"] is False
