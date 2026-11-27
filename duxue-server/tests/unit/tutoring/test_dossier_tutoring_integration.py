import json

from app.application.commands.problem_solving import (
    ExecuteDossierSolveCommand,
)
from app.application.ports.companion import RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from app.infrastructure.persistence.models import (
    Guardian,
    GuardianWard,
    ProblemDossierRecord,
    TutoringProblem,
    User,
    Ward,
)


def _seed_ward(db) -> Ward:
    ug = User(type="guardian")
    uw = User(type="ward")
    db.add_all([ug, uw])
    db.flush()
    g = Guardian(id=ug.id, email="dt_g@example.com", name="家长")
    w = Ward(id=uw.id, display_name="高三小林", grade_stage="high_school")
    db.add_all([g, w])
    db.flush()
    db.add(GuardianWard(guardian_id=g.id, ward_id=w.id))
    db.flush()
    return w


class AllowAllSafety:
    def blocks_input(self, *, text: str) -> bool:
        return False

    def blocks_output(self, *, text: str | None) -> bool:
        return False


class HighConfidenceSolverDouble:
    def extract_stem(self, *, text: str, images: list[str], independent_reread: bool = False) -> dict | None:
        return {"subject": "math", "raw_text": text, "subproblems": ["(1)"]}

    def solve_route(self, *, stem, images: list[str], route_hint: str) -> dict | None:
        return {
            "subject": "math",
            "final_answers": {"(1)": "x = 2"},
            "scoring_points": [{"id": "SP1", "step": "移项得 2x=4", "points": 2}],
            "implicit_constraints": [{"id": "I1", "expression": "x > 0", "description": "正数条件"}],
            "approaches": [
                {
                    "id": "A1",
                    "name": "代数移项法",
                    "milestones": [
                        {
                            "id": "M1",
                            "goal": "移项合并同类项得 2x - 4 = 0",
                            "check_kind": "symbolic_equivalence",
                            "canonical_target": "{2}",
                            "verify_request": {
                                "op": "solve",
                                "args": {"equations": ["2*x - 4"], "variables": ["x"]},
                                "symbols": [{"name": "x", "domain": "real"}],
                                "assumptions": [],
                            },
                        }
                    ],
                }
            ],
        }


class RecordingTutorModel:
    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.envelopes: list[dict] = []

    def complete(self, *, envelope: dict, instruction: str, recent_utterances=None, current_images=None, repair_error=None, observations=None) -> dict:
        self.envelopes.append(envelope)
        return self.replies.pop(0)


class InspectingJudge:
    def __init__(self, *, affirms_student_answer: bool = False):
        self.affirms = affirms_student_answer
        self.summaries: list[str] = []

    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, images=None):
        self.summaries.append(problem_summary or "")
        return {
            "leaks": False,
            "reason": "none",
            "answer_protected": True,
            "affirms_student_answer": self.affirms,
        }

    def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
        return True


def test_first_turn_nonblocking_when_dossier_pending_then_second_turn_adopts_ready_dossier(db):
    ward = _seed_ward(db)
    enqueued_ids: list[str] = []

    tutor_model = RecordingTutorModel(
        [
            # Turn 1: dossier is still pending (worker hasn't finished within 0s budget) -> safe Socratic icebreaker
            {
                "act": "guide",
                "content": "我们先一起读题确认条件：已知正数 $x$ 满足 $2x - 4 = 0$，你准备先怎么移项？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "移项整理方程",
                },
            },
            # Turn 2: background worker finished -> tutor receives ready dossier in envelope & advances student progress!
            {
                "act": "guide",
                "content": "移项得到 $2x = 4$ 非常准确！最后一步除以系数就能算出 $x$ 了。",
                "turn": {
                    "type": "work",
                    "relation": "same",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "2x = 4",
                    "completed_milestone_id": "M1",
                    "next_subgoal": "求出 x",
                },
            },
        ]
    )
    judge = InspectingJudge(affirms_student_answer=False)
    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=judge,
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda did, *_a: enqueued_ids.append(did),
        first_turn_solve_budget_seconds=0.0,
    )

    # Turn 1: non-blocking while dossier is pending
    out1 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-d1",
            run_id="r-1",
            turn_id="t-1",
            turn={"content": "已知正数 x 满足 2x - 4 = 0，求 x"},
        )
    )
    assert out1.next_interaction["act"] == "guide"
    assert len(enqueued_ids) == 1
    prob = db.query(TutoringProblem).one()
    assert prob.dossier_id == enqueued_ids[0]
    dossier_row = db.get(ProblemDossierRecord, prob.dossier_id)
    assert dossier_row is not None and dossier_row.status == "pending"

    # Simulate background `solving` Celery worker completing T2 high-confidence solve
    dossier_row.tier = "T2"
    db.flush()
    ExecuteDossierSolveCommand(
        db,
        solver=HighConfidenceSolverDouble(),
        math_engine=SubprocessMathEngineAdapter(),
    ).execute(dossier_id=prob.dossier_id, images=[])

    # Turn 2: automatically reads ready high-confidence dossier & records student milestone progress
    out2 = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-d1",
            run_id="r-2",
            turn_id="t-2",
            context_refs=out1.context_refs,
            turn={"content": "我先移项得到 2x = 4"},
        )
    )
    assert out2.next_interaction["act"] == "guide"
    assert "problem_dossier" in tutor_model.envelopes[1]
    assert tutor_model.envelopes[1]["problem_dossier"]["confidence"] == "high"

    # Anti-false-positive guardrail: intermediate milestone canonical_target `{2}` or goal NEVER sent to leak-judge,
    # ONLY `verified_final_answers` when confidence == "high"!
    judge_payload = json.loads(judge.summaries[-1])
    inner_problem = json.loads(judge_payload["problem"]) if isinstance(judge_payload.get("problem"), str) else judge_payload
    assert inner_problem.get("verified_final_answers") == {"(1)": "x = 2"}
    assert "移项合并同类项" not in judge.summaries[-1]

    # Student's personal progress stored on TutoringProblem, NOT mutating ProblemDossierRecord
    db.refresh(prob)
    assert prob.milestone_progress == {"M1": "completed"}


def test_pending_dossier_does_not_override_independent_judge_allow(db):
    ward = _seed_ward(db)
    # Create a pending/low-confidence dossier (no background worker run yet, and tutor did NOT call math tool)
    tutor_model = RecordingTutorModel(
        [
            # Primary attempt: recklessly affirms student's unverified answer while dossier is still pending!
            {
                "act": "guide",
                "content": "你算得完全正确，答案就是 7！",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "submitted",
                    "evidence": "我猜答案是 7",
                },
            },
            # Repair attempt after code confidence gate denies unverified affirmation -> switches to Socratic check!
            {
                "act": "guide",
                "content": "我们可以把 $x=7$ 代回原方程左边算一算，看看两边是否相等？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "提出 x=7",
                    "next_subgoal": "代回原方程检验",
                },
            },
        ]
    )

    class TwoStepJudge:
        def __init__(self):
            self.calls = 0

        def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None, images=None):
            self.calls += 1
            # First candidate affirms student answer; second candidate asks student to verify
            return {
                "leaks": False,
                "reason": "none",
                "answer_protected": True,
                "affirms_student_answer": self.calls == 1,
            }

        def check_math(self, *, text: str, context: dict, images: list[str]) -> bool | None:
            return True

    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=TwoStepJudge(),
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda *_a: None,
        first_turn_solve_budget_seconds=0.0,
    )
    out = wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-gate",
            run_id="r-gate",
            turn_id="t-gate",
            turn={"content": "复杂的超越方程 ln x + x = 8，我算出来是 7 对不对？"},
        )
    )
    # Missing dossier evidence cannot turn a Judge allow into an explicit violation.
    assert "完全正确" in out.next_interaction["content"]
    assert len(tutor_model.envelopes) == 1


def test_step_evaluate_math_tool_does_not_unlock_optimality_affirmation_on_unbacked_first_turn(db):
    """Bridge-crossing regression: computing route cost `2+1+10+2+4=19` proves only the
    step arithmetic, NOT that 19 minutes is optimal; unbacked final affirmation must be denied."""
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit

    ward = _seed_ward(db)
    _ = ward

    class BridgeTutorModel:
        def __init__(self):
            self.calls = 0

        def complete(self, *, envelope, instruction, recent_utterances=None, current_images=None, repair_error=None, observations=None):
            self.calls += 1
            if self.calls == 1:
                # Call math evaluate for local sum 2+1+10+2+4 -> 19
                return {
                    "tool": "math",
                    "args": {"op": "evaluate", "args": {"expression": "2 + 1 + 10 + 2 + 4"}},
                }
            if self.calls == 2:
                # Recklessly affirm 19 is optimal despite having only step-sum arithmetic!
                return {
                    "act": "guide",
                    "content": "你算得完全对，19 分钟就是最短时间！",
                    "turn": {
                        "type": "work",
                        "relation": "new",
                        "depth": "reasoning",
                        "student_move": "attempt",
                        "progress": "submitted",
                        "evidence": "19 分钟",
                    },
                }
            # After confidence gate blocks optimality affirmation, confirm only the arithmetic step & guide
            return {
                "act": "guide",
                "content": "按你这条路线加起来确实是 19 分钟，不过可以想想能不能让最慢的两个人一起过桥来省时间？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "attempt",
                    "progress": "some",
                    "evidence": "19 分钟路线",
                    "next_subgoal": "比较最慢两人同行的耗时",
                },
            }

    class BridgeJudge:
        def __init__(self):
            self.calls = 0

        def leaks(self, *, text, task_title, problem_summary, images=None):
            self.calls += 1
            return {
                "leaks": self.calls == 1,
                "reason": "premature_conclusion" if self.calls == 1 else "none",
                "answer_protected": True,
                "affirms_student_answer": self.calls == 1,
            }

        def check_math(self, *, text, context, images):
            return True

    tools = TutorToolbox(
        db,
        tutoring_session_id=None,
        problem=None,
        task_title=None,
        task_active=False,
        window=[],
        math_engine=SubprocessMathEngineAdapter(),
    )
    result = run_tutor_turn(
        BridgeTutorModel(),
        envelope={"_enforce_confidence_gate": True},
        instruction="过桥题 1,2,5,10 分钟，学生问 19 分钟是不是最短？",
        window=[],
        images=[],
        tools=tools,
        permit=TutorPermit(answer_protected=False, attempt_summary=AttemptSummary()),
        leak_judge=BridgeJudge(),
        task_title=None,
        problem_summary='{"current_request": "19 分钟是不是最短？"}',
    )
    assert result.leak_retried is True
    assert result.vetting is not None and result.vetting.failure is None
    assert "最慢的两个人一起过桥" in result.vetting.candidate.content


def test_deferred_dossier_creation_skips_direct_chitchat_and_worksheet_batch(db):
    """P1-1: Knowledge/chitchat/direct turns and multi-question worksheet checks must NEVER
    enqueue background ProblemDossier solving; only vetted reasoning work creates one."""
    from tests.support.fakes import tutor_raw

    ward = _seed_ward(db)
    enqueued_ids: list[str] = []

    tutor_model = RecordingTutorModel(
        [
            # 1) Pure chitchat / conversation -> 0 enqueue
            tutor_raw(act="answer", relation="none", topic="chitchat", content="你好呀！今天想先看哪一科的作业？"),
            # 2) Direct concept/knowledge question (T0) -> 0 enqueue
            tutor_raw(act="answer", relation="none", topic="atomic_lookup", content="光合作用主要在叶绿体里进行，把二氧化碳和水转化为有机物并释放氧气。"),
            # 3) Reasoning work -> enqueues exactly 1 dossier
            {
                "act": "guide",
                "content": "这道题我们先设未知数，你觉得应该设哪个量为 x？",
                "turn": {
                    "type": "work",
                    "relation": "new",
                    "depth": "reasoning",
                    "student_move": "request_hint",
                    "next_subgoal": "设未知数",
                },
            },
        ]
    )
    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=InspectingJudge(affirms_student_answer=False),
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda did, *_a: enqueued_ids.append(did),
        first_turn_solve_budget_seconds=0.0,
    )

    wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-p11",
            run_id="r-p11-1",
            turn_id="t-p11-1",
            turn={"content": "你好"},
        )
    )
    assert enqueued_ids == []

    wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-p11",
            run_id="r-p11-2",
            turn_id="t-p11-2",
            turn={"content": "光合作用的场所是哪里？"},
        )
    )
    assert enqueued_ids == []

    wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-p11",
            run_id="r-p11-3",
            turn_id="t-p11-3",
            turn={"content": "甲乙两人相向而行，3小时相遇，求速度"},
        )
    )
    assert len(enqueued_ids) == 1


def test_tutor_turn_gateway_disables_thinking_on_ready_high_dossier_and_strips_internal_flag(monkeypatch):
    """P2: `ready + high` follow-up turns disable Thinking on QwenTutorTurnGateway and never
    leak `_disable_thinking` into the LLM prompt context."""
    from dataclasses import replace

    from app.infrastructure.ai import components
    from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway

    captured: list[dict] = []

    class FakeResult:
        def unwrap(self):
            return {"act": "guide", "content": "ok"}

    def fake_invoke(*, spec, user, client=None, settings_obj=None):
        captured.append({"enable_thinking": spec.enable_thinking, "thinking_budget": spec.thinking_budget, "user": user})
        return FakeResult()

    monkeypatch.setattr(components, "invoke_agent_component", fake_invoke)
    thinking_spec = replace(
        components.COMPONENTS.get("tutoring.turn"),
        enable_thinking=True,
        thinking_budget=2048,
    )
    gw = QwenTutorTurnGateway(spec=thinking_spec)

    # Normal turn: keeps thinking enabled
    gw.complete(envelope={"subject": "math"}, instruction="第一步")
    assert captured[0]["enable_thinking"] is True
    assert captured[0]["thinking_budget"] == 2048

    # Follow-up turn with ready+high dossier: disables thinking & strips internal key
    gw.complete(envelope={"subject": "math", "_disable_thinking": True}, instruction="第二步")
    assert captured[1]["enable_thinking"] is False
    assert captured[1]["thinking_budget"] is None
    assert "_disable_thinking" not in str(captured[1]["user"])


def test_first_image_lookup_reuses_the_created_request_fingerprint(db):
    from app.application.commands.problem_solving import RequestSolveCommand

    ward = _seed_ward(db)
    requests = []

    def enqueue(dossier_id, images):
        requests.append(dossier_id)

    workflow = TutoringWorkflow(db, dossier_enqueue_fn=enqueue)
    args = dict(
        ward_id=ward.id,
        problem_row=None,
        content="帮我看第 1 题",
        images=["image-a"],
        attachment_keys=[],
        tutoring_intent=None,
    )
    assert workflow._resolve_active_dossier(**args) == (None, None)
    assert requests == []
    dossier = RequestSolveCommand(db, enqueue_fn=enqueue).execute(
        ward_id=ward.id, text=args["content"], images=args["images"],
    )
    row = db.get(ProblemDossierRecord, dossier.dossier_id)
    row.status = "ready"
    db.flush()
    found, _ = workflow._resolve_active_dossier(**args)
    assert found.dossier_id == dossier.dossier_id
    assert workflow._resolve_active_dossier(**{**args, "images": ["image-b"]}) == (None, None)
    assert workflow._resolve_active_dossier(**{**args, "content": "帮我看第 2 题"}) == (None, None)
    assert requests == [dossier.dossier_id]


def test_p2_ready_medium_dossier_disables_thinking_without_unlocking_verdict_gate(db):
    """Ready + medium dossier follow-up disables thinking while keeping high-only verdict gate."""
    from app.application.commands.problem_solving import RequestSolveCommand
    from tests.support.fakes import tutor_raw

    ward = _seed_ward(db)
    question = "小明 5 分钟走 400 米，照这个速度 8 分钟走多少米？"
    dossier = RequestSolveCommand(db, enqueue_fn=lambda *_a: None).execute(
        ward_id=ward.id, text=question, images=[],
    )
    row = db.get(ProblemDossierRecord, dossier.dossier_id)
    row.status = "ready"
    row.confidence = "medium"
    row.dossier_json = {
        "dossier_id": dossier.dossier_id,
        "status": "ready",
        "confidence": "medium",
        "stem": {"subject": "math", "raw_text": question, "subproblems": ["(1)"]},
        "approaches": [],
    }
    db.flush()

    tutor_model = RecordingTutorModel([tutor_raw(act="guide", content="我们先列一下关系式看看。")])
    wf = TutoringWorkflow(
        db,
        turn_model=tutor_model,
        leak_judge=InspectingJudge(affirms_student_answer=False),
        safety_screening=AllowAllSafety(),
        math_engine=SubprocessMathEngineAdapter(),
        dossier_enqueue_fn=lambda *_a: None,
        first_turn_solve_budget_seconds=0.0,
    )
    wf.invoke(
        RunInvocation(
            agent_type="tutoring",
            ward_id=ward.id,
            thread_id="th-p2-med",
            run_id="run-p2-med",
            turn_id="turn-p2-med",
            command_id="cmd-p2-med",
            attempt=1,
            turn={"content": question},
        )
    )
    assert len(tutor_model.envelopes) == 1
    env = tutor_model.envelopes[0]
    assert env.get("_thinking_effort") == "off"
    assert "_disable_thinking" not in env
    assert env.get("_dossier_gate", {}).get("allows_verdict_assertion") is False


def test_data_url_caches_immutable_storage_reads_and_skips_mocks(monkeypatch):
    from app.application.commands import task_intake

    calls: list[str] = []

    class FakeStorage:
        def read_bytes(self, key: str) -> bytes:
            calls.append(key)
            return b"png-bytes"

    task_intake.clear_data_url_cache()
    monkeypatch.setattr(task_intake, "storage", FakeStorage())
    first = task_intake._data_url("ward/w1/companion/img.png")
    second = task_intake._data_url("ward/w1/companion/img.png")
    assert first == second and first.startswith("data:image/png;base64,")
    assert calls == ["ward/w1/companion/img.png"]
    task_intake.clear_data_url_cache()


def test_build_tutor_instruction_omits_duplicate_history_candidates():
    import json

    from app.application.workflows.tutor_turn import build_tutor_instruction
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy

    raw = build_tutor_instruction(
        content="In charge of 是什么意思？",
        permit=TutorPermitPolicy.permit(None),
        history_candidates=[{"ref": "u0", "author": "ward", "text": "太阳系有几大行星？"}],
        tutoring_intent=None,
    )
    parsed = json.loads(raw)
    assert "history_candidates" not in parsed
    assert parsed["student_said"] == "In charge of 是什么意思？"


def test_upgrade_tutoring_reliability_syncs_worksheet_batch_and_dedupes_leak_judge():
    from pathlib import Path

    from app.agent_specs.admin_bundle import compile_bundle
    from scripts.upgrade_blueprint_steps import upgrade as add_steps
    from scripts.upgrade_math_bundle import upgrade as add_blueprint
    from scripts.upgrade_tutoring_reliability import upgrade

    base = add_steps(add_blueprint(json.loads(Path("tests/fixtures/admin-release.json").read_text()), gaokao=True))
    bundle = base["bundle"]
    files = bundle["files"]
    # Simulate legacy stem-extract prompt (without worksheet_batch) & dirty leak-judge (7x duplicate line)
    files["agents/tutoring.stem-extract.json"]["prompt"]["template"] = "旧版转写提示词，不含批量标记。"
    lj_tpl = files["gates/tutoring.leak-judge.json"]["prompt"]["template"]
    files["gates/tutoring.leak-judge.json"]["prompt"]["template"] = (
        lj_tpl + "\n" + "\n".join(["保持表述准确。"] * 7)
    )
    source = {**base, "bundle": bundle, "digest": compile_bundle(bundle).digest}

    upgraded = upgrade(source)
    out_files = upgraded["bundle"]["files"]
    assert "worksheet_batch" in out_files["agents/tutoring.stem-extract.json"]["prompt"]["template"]
    assert out_files["gates/tutoring.leak-judge.json"]["prompt"]["template"].count("保持表述准确。") == 1
    # Idempotency check
    second = upgrade(upgraded)
    assert second["digest"] == upgraded["digest"]
