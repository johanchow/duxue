import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.debug_contracts import debug_capabilities
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.application.workflows import guardian_mentor as mentor
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded
from scripts.upgrade_blueprint_steps import upgrade as stage_blueprint
from scripts.upgrade_guardian_mentor_review import upgrade
from scripts.upgrade_math_bundle import upgrade as provision


@pytest.fixture(scope="module")
def releases():
    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    old = stage_blueprint(provision(source, guardian_mentor=True, gaokao=True))
    new = upgrade(old, parent=True)
    assert new["digest"] == upgrade(new, parent=True)["digest"]
    assert [path for path, value in new["bundle"]["files"].items()
            if old["bundle"]["files"][path] != value] == ["workflows/guardian-mentor.json"]
    assert "guardian-mentor" in debug_capabilities(compile_bundle(new["bundle"]).catalog)["workflows"]
    return old, new


def test_compiler_rejects_skipped_blueprint(releases):
    bundle = deepcopy(releases[1]["bundle"])
    graph = bundle["files"]["workflows/guardian-mentor.json"]
    graph["edges"].append({"from": "guardian-mentor.prepare", "to": "guardian-mentor.explain"})
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    with pytest.raises(ValueError, match="guardian mentor parent topology"):
        compile_bundle(bundle)


@pytest.mark.parametrize("failure, repair", [
    (None, None), (None, "format"), (None, "coverage"), (None, "relocate"), (None, "related"),
    ("image_unclear", None), ("invalid_distance_read", None), ("reread_unavailable", None),
])
def test_guardian_distance_evidence_is_bound_to_crop_and_checked_before_delivery(
    releases, monkeypatch, failure, repair,
):
    from app.agent_specs.blueprint_steps import BACKUP, EXTRACT, PLANNER_ID, REREAD
    from app.agent_specs.image_refs import image_ref
    from app.application.ports.image_inspection import InspectImageResult
    from app.infrastructure.ai import components
    from app.infrastructure.media.pillow_crop import PillowImageInspector

    source = releases[1]
    candidate = upgrade(source, distance_evidence=True)
    low = upgrade(source, distance_low_effort=True)
    assert candidate["digest"] == upgrade(candidate, distance_evidence=True)["digest"]
    changed = [
        key for key, value in candidate["bundle"]["files"].items()
        if low["bundle"]["files"][key] != value
    ]
    assert changed == [f"agents/{PLANNER_ID}.json"]
    image = "https://example.invalid/paper.png"
    other = "https://example.invalid/other.png"
    ref = image_ref(image)
    other_ref = image_ref(other)
    called = []
    crops = []

    def inspect(self, req, *, authorized_images):
        assert authorized_images == {ref: image, other_ref: other}
        crops.append(req)
        return InspectImageResult(
            status="unique", image_ref=req.image_ref, bbox=req.bbox, crop_ref=f"crop_{len(crops)}",
            crop_data_url="data:image/png;base64,AAAA",
        )

    adjacent_labels = repair == "format"
    start, middle, end = ("P", "Q", "R") if adjacent_labels else ("A", "B", "C")
    first, second = ("d", "s") if adjacent_labels else ("x_1", "x_2")
    second_start = middle if adjacent_labels else start
    spacing = second if adjacent_labels else f"{second}-{first}"
    full_distance = f"{first}+{second}" if adjacent_labels else second
    wrong_distance = second if adjacent_labels else f"{first}+{second}"
    parts = [
        {"part": part, "kind": kind, "start": start, "middle": middle, "end": end}
        for part, kind in [("2", "adjacent_spacing"), ("3", "midpoint_velocity")]
    ]

    def invoke(*, spec, user, **kwargs):
        seen = spec.component_id
        called.append(seen)
        data = json.loads(user[0]["text"])
        if seen in {EXTRACT, REREAD}:
            raw = {
                "tier": "T1", "subject": "physics", "shared_stem_summary": "确认纸带端点",
                "subproblems": ["1", "2", "3"], "needs_student_confirmation": False,
            }
            if repair == "related":
                raw["subproblems"] = ["（2）根据图甲判断相邻间距。", "（3）由图甲求中点速度。"]
            if data.get("distance_stage") == "locate" or (seen == EXTRACT and repair != "relocate"):
                raw["distance_targets"] = [{
                    "figure": "图甲", "image_id": 2 if repair == "relocate" and not data.get("distance_relocate") else 1,
                    "bbox": {"x0": 0.4, "x1": 0.9, "y0": 0.3, "y1": 0.7},
                    "parts": [{key: row[key] for key in ("part", "kind")} for row in parts],
                    "symbols": [first, second],
                }]
                if not data.get("distance_relocate"):
                    raw["distance_targets"].append({"figure": "图乙", "image_id": 2, "symbols": ["3.59", "8.00"]})
                if repair == "related":
                    raw["distance_targets"][0]["parts"].pop(0)
            elif seen == REREAD:
                assert data["distance_target"]["figure"] == "图甲"
                assert len([part for part in user if part["type"] == "image_url"]) == 1
                if failure == "reread_unavailable":
                    return Mock(unwrap=lambda: None)
                if repair == "related":
                    assert set(data["related_subproblems"]) == {"2"}
                labels = [
                    {"symbol": first, "start": start, "end": middle},
                    {"symbol": second, "start": second_start, "end": end},
                ]
                if repair == "relocate" and crops[-1].image_ref == other_ref:
                    labels = [{"symbol": "3.59", "start": "A", "end": "B"}]
                if failure == "invalid_distance_read" or (repair == "format" and not data.get("distance_format_errors")):
                    labels[0]["value"] = "0.10"
                raw["distance_reading"] = {
                    "status": "image_unclear" if failure == "image_unclear" else "read",
                    "labels": labels,
                    "questions": [{**parts[0], "interval_symbol": "0.10s"}, {**parts[1], "interval_symbol": "T"}],
                }
                if repair == "coverage" and not data.get("distance_format_errors"):
                    raw["distance_reading"]["questions"].pop(0)
        elif seen in {PLANNER_ID, BACKUP}:
            evidence = data["stem"]["distance_evidence"]
            if failure:
                assert {row["reason"] for row in evidence["unresolved_parts"]} == {failure}
                return Mock(unwrap=lambda: {
                    "final_answers": {"1": "独立答案", "(2)": "不得交付"},
                    "approaches": [{"id": "A", "name": "步骤", "milestones": [
                        {"id": "M", "goal": "独立题目", "check_kind": "conceptual_rubric"},
                    ]}],
                })
            assert evidence["sources"][0]["image_ref"] == ref
            if seen == BACKUP:
                assert data["contradiction_feedback"]["contradictions"][0]["part"] == "3"
            raw = {
                "final_answers": {"2": "左端", "3": "中点速度"},
                "approaches": [{"id": "A", "name": "读纸带", "milestones": [
                    {"id": "M", "goal": "比较间距", "check_kind": "conceptual_rubric"},
                ]}],
                "distance_claims": {
                    "[[distance_1]]": {"first_interval": first, "second_interval": spacing},
                    "[[distance_2]]": {
                        "velocity": f"({wrong_distance if seen == PLANNER_ID else full_distance})/(2*T)",
                    },
                },
            }
        else:
            evidence = data["verified_solution"]["stem"]["distance_evidence"]
            assert evidence["formulas"][1]["expected"]["velocity"] == f"({full_distance})/(2*T)"
            raw = {"act": "explain", "content": "（2）$$[[distance_1]]$$，左端。\n（3）[[distance_2]]。\n复核 $[[distance_2]]$。"}
        return Mock(unwrap=lambda: raw)

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MATH_ENGINE_MODE", "subprocess")
    monkeypatch.setattr(components, "invoke_agent_component", invoke)
    monkeypatch.setattr(PillowImageInspector, "inspect", inspect)
    trace = Recorder()
    with use_definitions(compile_bundle(candidate["bundle"]).catalog), trace.capture():
        result = mentor.explain_for_guardian(
            guardian_id=f"distance-test-{failure}-{repair}", content="请讲解纸带实验",
            attachment_keys=[], window=[], images=[image, other], rows=[],
        )
    assert [crop.image_ref for crop in crops] == ([other_ref, ref] if repair == "relocate" else [ref])
    if failure:
        assert result["act"] == "explain"
        assert "独立答案" in result["content"]
        assert "不得交付" not in result["content"]
        assert ("请补拍图甲" in result["content"]) == (failure == "image_unclear")
        assert mentor.MENTOR_EXPLAIN_ID not in called
    else:
        assert result["act"] == "explain"
        reads = {None: [REREAD], "related": [REREAD], "format": [REREAD, REREAD], "coverage": [REREAD, REREAD],
                 "relocate": [EXTRACT, REREAD, EXTRACT, REREAD]}
        assert called == [EXTRACT] + reads[repair] + [
            PLANNER_ID, BACKUP, mentor.MENTOR_EXPLAIN_ID,
        ]
        assert f"{middle}{end}={spacing}" in result["content"]
        assert rf"\dfrac{{{full_distance}}}{{2T}}" in result["content"]
        assert "[[distance_" not in result["content"]
        assert "$$$" not in result["content"]


@pytest.mark.parametrize(("case", "calls", "act"), [
    ("ok", 1, "explain"), ("retry", 2, "explain"), ("invalid", 2, "unavailable"),
    ("transport", 1, "unavailable"), ("unsafe_output", 1, "safety"),
    ("unsafe_input", 0, "safety"), ("ambiguous", 0, "clarify"), ("deadline", 1, "timeout"),
])
def test_turn_matches_legacy_and_records_child(releases, case, calls, act, monkeypatch):
    from app.application.workflows.guardian_experience import experience_turn
    from app.infrastructure.security.experience_tokens import unseal

    monkeypatch.setattr(mentor.LocalSafetyScreening, "blocks_input", lambda self, **kw: case == "unsafe_input")
    monkeypatch.setattr(mentor.LocalSafetyScreening, "blocks_output", lambda self, **kw: case == "unsafe_output")
    monkeypatch.setattr("app.application.workflows.guardian_experience._image", lambda *args: None)
    comparable = []
    for record in releases:
        solver = Mock()
        solver.extract_stem.return_value = {"tier": "T1", "raw_text": "原题"}
        solver.solve_route.return_value = {"final_answers": {"main": "3"}}
        monkeypatch.setattr(mentor, "QwenProblemSolverGateway", lambda settings: solver)
        response = {"content": "完整解析", "act": "explain"}
        invalid = ModelGatewayError("invalid_model_candidate")
        responses = {"retry": [invalid, response], "invalid": [invalid, invalid],
                     "transport": [ModelGatewayError("model_transport_error")],
                     "deadline": [ModelTimeBudgetExceeded()]}
        gateway = Mock()
        gateway.explain.side_effect = responses.get(case, [response])
        monkeypatch.setattr(mentor, "QwenMentorExplainGateway", lambda settings: gateway)
        recording = Recorder()
        with use_definitions(compile_bundle(record["bundle"]).catalog), recording.capture():
            try:
                result = experience_turn(
                    guardian_id="parent-" + case, content="请讲解", attachment_keys=["missing"] if case == "ambiguous" else [],
                    state={}, mode="guardian_explain",
                )
            except ModelTimeBudgetExceeded:
                result = {"act": "timeout"}
        assert result["act"] == act
        assert gateway.explain.call_count == calls
        assert solver.extract_stem.call_count == int(calls > 0)
        assert solver.solve_route.call_count == int(calls > 0)
        if "state_token" in result:
            state = unseal(result.pop("state_token"), "parent-" + case, mentor.MENTOR_PURPOSE)
            comparable.append((result, [row["text"] for row in state["window"]]))
        if record is releases[1]:
            nodes = [e for e in recording.events if e.get("workflow_id") == "guardian-mentor" and e.get("node_id")]
            assert nodes[0]["node_id"] == "guardian-mentor.prepare"
            if calls:
                child = next(e for e in nodes if e["node_id"] == "guardian-mentor.blueprint")
                assert any(e.get("workflow_id") == "tutoring-blueprint" and e["parent_id"] == child["id"]
                           for e in recording.events)
            assert sum(e["node_id"] == "guardian-mentor.explain" for e in nodes) == calls
    if comparable:
        assert comparable[0] == comparable[1]


def test_http_turn_obeys_parent_retry_budget(client, db, releases, monkeypatch):
    from app.infrastructure.persistence.models import Guardian, User, uid
    from app.infrastructure.security.tokens import create_access_token

    identifier = uid()
    db.add(User(id=identifier, type="guardian"))
    db.flush()
    db.add(Guardian(id=identifier, name="Parent", email="mentor-parent@example.com", role="guardian"))
    db.commit()
    bundle = deepcopy(releases[1]["bundle"])
    bundle["files"]["workflows/guardian-mentor.json"]["limits"]["model_calls"] = 1
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    gateway = Mock(side_effect=ModelGatewayError("invalid_model_candidate"))
    monkeypatch.setattr(mentor.QwenMentorExplainGateway, "explain", gateway)
    monkeypatch.setattr(mentor.QwenProblemSolverGateway, "extract_stem", lambda *a, **kw: {"tier": "T0"})
    with use_definitions(compile_bundle(bundle).catalog):
        result = client.post("/guardian/experience/turn", headers={
            "Authorization": f"Bearer {create_access_token(user_id=identifier, role='guardian')}",
        }, json={"content": "解释一个概念", "mode": "guardian_explain"})
    assert result.status_code == 200
    assert result.json()["act"] == "unavailable"
    assert gateway.call_count == 1


@pytest.mark.parametrize(("task", "tier", "unclear", "enabled", "expected_direct"), [
    ("english_writing", "T1", False, True, True),
    ("solve", "T1", False, True, False),
    ("english_language", "T1", False, True, False),
    (None, "T1", False, True, False),
    ("english_writing", "T2", False, True, False),
    ("english_writing", "T1", True, True, False),
    ("english_writing", "T1", False, False, False),
])
def test_opt_in_language_route(releases, task, tier, unclear, enabled, expected_direct):
    from app.application.commands.problem_solving import execute_blueprint
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    trial = upgrade(releases[1], latency_trial=True)
    assert trial["digest"] == upgrade(trial, latency_trial=True)["digest"]
    raw = dict(subject="english", tier=tier, raw_text="指定题组", guardian_task=task,
               needs_student_confirmation=unclear)
    solver = Mock()
    solver.extract_stem.return_value = raw
    solver.solve_route.return_value = {"final_answers": {"main": "C"}}
    recording = Recorder()
    with use_definitions(compile_bundle(trial["bundle"]).catalog), recording.capture():
        result = execute_blueprint(stem=StructuredStem(subject="general", raw_text="题面"),
                                   solver=solver, images=["image"], math_engine=None,
                                   question="指定题组", allow_language_direct=enabled)
    direct = any(e.get("selected") and e.get("condition_id") == "mentor_language" for e in recording.events)
    assert bool(direct) == expected_direct
    if direct:
        solver.solve_route.assert_not_called()
        assert result.confidence == "low"
        assert not result.mentor_projection()["verified_final_answers"]


def test_trial_keeps_guardian_scope_on_solver_calls(releases, monkeypatch):
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    record = upgrade(releases[1], latency_trial=True)
    request = "请只解答图中第1至10题"
    solver = QwenProblemSolverGateway(guardian_request=request)
    sent = []

    def invoke(*, spec, user, retry_on_timeout):
        body = json.loads(user[0]["text"])
        sent.append(body)
        return {"subject": "english", "guardian_task": "solve", "target_scope": "第1至10题", "tier": "T1",
                "shared_stem_summary": "图中另有第11至20题", "needs_student_confirmation": False}

    monkeypatch.setattr(solver, "_invoke_once", invoke)
    with use_definitions(compile_bundle(record["bundle"]).catalog):
        images = ["data:image/jpeg;base64,AA=="]
        raw = solver.extract_stem(text=request, images=images)
        solver.solve_route(stem=StructuredStem.from_dict(raw), images=images, route_hint="T1")
    assert sent[0]["guardian_request"] == sent[1]["guardian_request"] == request
    assert raw["guardian_task"] == "solve"
    assert raw["target_scope"] == sent[1]["target_scope"] == "第1至10题"
    assert "guardian_routing_contract" in sent[0]
    assert "guardian_routing_contract" not in sent[1]


def test_low_effort_is_scoped_to_guardian_t1_primary(releases, monkeypatch):
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    record = upgrade(releases[1], low_effort_trial=True)
    specs = []
    def capture(self, *, spec, **kwargs):
        specs.append(spec)
        return {}

    monkeypatch.setattr(QwenProblemSolverGateway, "_invoke_once", capture)
    with use_definitions(compile_bundle(record["bundle"]).catalog):
        for guardian, hint in [("问题", "T1"), (None, "T1"), ("问题", "T2_algebraic"), ("问题", "T1_backup")]:
            QwenProblemSolverGateway(guardian_request=guardian).solve_route(
                stem=StructuredStem("physics", "题面"), images=[], route_hint=hint,
            )
        from app.infrastructure.ai.components import COMPONENTS
        expected = [COMPONENTS.get(spec.component_id).thinking_effort for spec in specs]
    expected[0] = "low"
    assert [spec.thinking_effort for spec in specs] == expected
    from app.infrastructure.ai.thinking_policy import resolve_provider_thinking
    params = resolve_provider_thinking(specs[0].model, effort=specs[0].thinking_effort)
    assert params.enable_thinking and params.effective_effort == "low"
