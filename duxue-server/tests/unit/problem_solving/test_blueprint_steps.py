import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.blueprint_steps import BACKUP, PLANNER_ID
from app.agent_specs.catalog import load_catalog
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.application.workflows.guardian_mentor import _solve_for_mentor
from app.infrastructure.ai.components import invoke_json_component
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from scripts.upgrade_blueprint_steps import upgrade
from scripts.upgrade_math_bundle import upgrade as add_blueprint


@pytest.fixture(scope="module")
def staged():
    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    record = upgrade(add_blueprint(source, gaokao=True))
    assert upgrade(record)["digest"] == record["digest"]
    return compile_bundle(record["bundle"]).catalog


def _good_math_route():
    return {
        "subject": "math",
        "final_answers": {"(1)": "2*x"},
        "approaches": [
            {
                "id": "A1",
                "name": "求导法",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "2*x",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }


def _contradicted_math_route():
    return {
        "subject": "math",
        "final_answers": {"(1)": "9*x"},
        "approaches": [
            {
                "id": "A1",
                "name": "错误初算",
                "milestones": [
                    {
                        "id": "M1",
                        "goal": "求导",
                        "check_kind": "symbolic_equivalence",
                        "canonical_target": "9*x",
                        "verify_request": {
                            "op": "differentiate",
                            "args": {"expression": "x**2", "variable": "x", "order": 1},
                            "symbols": [{"name": "x", "domain": "real"}],
                            "assumptions": [],
                        },
                    }
                ],
            }
        ],
    }


def test_real_mentor_t0_and_t1_verified_and_t2_parallel_clear_image(staged):
    class Solver:
        def __init__(self, tier):
            self.tier = tier
            self.reread_called = False

        def extract_stem(self, *, independent_reread, **kwargs):
            if independent_reread:
                self.reread_called = True
            return {
                "tier": self.tier,
                "raw_text": "求 f(x)=x^2 的导数",
                "subproblems": ["(1)"],
                "needs_student_confirmation": False,
            }

        def solve_route(self, *, route_hint, **kwargs):
            component = BACKUP if route_hint in {"T1_backup", "T2_alternative"} else PLANNER_ID
            identity = load_catalog().component_identity(component)
            expected_node = {
                "T1": "ordinary",
                "T1_backup": "backup",
                "T2_algebraic": "primary",
                "T2_alternative": "alternative",
            }[route_hint]
            assert identity.node_id == "tutoring-blueprint." + expected_node
            return _good_math_route()

    # T0 short-circuits directly to finish
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(content="题面", images=[], solver=Solver("T0"), bank_lookup=None)
    assert [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}] == [
        "extract", "select", "finish"
    ]
    assert res.status == "ready" and res.tier == "T0"

    # T1 verified path -> finish (via verified edge)
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(content="题面", images=[], solver=Solver("T1"), bank_lookup=None)
    assert [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}] == [
        "extract", "select", "ordinary", "verify", "finish"
    ]
    assert res.status == "ready" and res.confidence == "medium"

    # T2 with clear image -> skips reread, runs primary & alternative in parallel, converges on verify_t2 -> finish
    solver_t2 = Solver("T2")
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(content="题面", images=["img"], solver=solver_t2, bank_lookup=None)
    steps = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}]
    assert solver_t2.reread_called is False
    assert steps[:2] == ["extract", "select"]
    assert set(steps[2:4]) == {"primary", "alternative"}
    assert steps[4:] == ["verify_t2", "finish"]
    assert res.status == "ready" and res.confidence == "high"


def test_t1_contradicted_switches_to_backup_and_reread_dispute_short_circuits(staged):
    class BackupSolver:
        def extract_stem(self, *, independent_reread, **kwargs):
            return {"tier": "T1", "raw_text": "求 f(x)=x^2 的导数", "subproblems": ["(1)"], "needs_student_confirmation": False}

        def solve_route(self, *, route_hint, feedback=None, **kwargs):
            if route_hint == "T1":
                return _contradicted_math_route()
            assert route_hint == "T1_backup"
            assert feedback and feedback["contradictions"]
            return _good_math_route()

    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(content="题面", images=[], solver=BackupSolver(), bank_lookup=None)
    assert [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}] == [
        "extract", "select", "ordinary", "verify", "backup", "verify_backup", "finish"
    ]
    assert res.status == "ready" and res.confidence == "medium" and res.evidence["used_backup"] is True

    # Unclear image flagged by extract -> reread -> disputed -> short-circuit to finish without running any solver
    class DisputedImageSolver:
        def extract_stem(self, *, independent_reread, **kwargs):
            if independent_reread:
                return {"raw_text": "求 f(x)=x^3 的导数", "needs_student_confirmation": False}
            return {"tier": "T2", "raw_text": "求 f(x)=x^2 的导数", "needs_student_confirmation": True}

        def solve_route(self, **kwargs):
            raise AssertionError("solver must not run after reread dispute short-circuit")

    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(content="题面", images=["img"], solver=DisputedImageSolver(), bank_lookup=None)
    assert [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}] == [
        "extract", "select", "reread", "reread_check", "finish"
    ]
    assert res.status == "low_confidence" and res.evidence["short_circuited"] is True


def test_prepared_worker_stem_resumes_at_selection(staged):
    from app.application.commands.problem_solving import solve_and_verify_problem
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    class Solver:
        def solve_route(self, *, route_hint, **kwargs):
            assert route_hint == "T1"
            return _good_math_route()

    trace = Recorder()
    with use_definitions(staged), trace.capture():
        result = solve_and_verify_problem(
            stem=StructuredStem(subject="math", raw_text="求 f(x)=x^2 导数", subproblems=("(1)",)),
            solver=Solver(),
            math_engine=SubprocessMathEngineAdapter(),
        )
    assert result.final_answers == {"(1)": "2*x"}
    assert result.status == "ready"
    node_events = [e for e in trace.events if e["kind"] in {"agent", "gate", "action"}]
    assert node_events[0]["node_id"] == "tutoring-blueprint.select"
    assert any(
        e["kind"] == "edge" and e.get("condition_id") == "has_verified_stem" and e.get("selected") is True
        for e in trace.events
    )
    assert result.evidence["stem_version"] == 1
    assert result.evidence["target_subproblems"] == ["(1)"]
    assert result.evidence["coverage"] == "complete"
    assert len(result.evidence["verified_assertions"]) == 1


def test_reread_checks_words_and_subquestions():
    from app.contexts.problem_solving.domain.dossier import (
        StructuredStem,
        compare_critical_conditions,
    )

    stem = StructuredStem("math", "从5个球中有放回抽取2次", ("求概率",))
    for other in (
        StructuredStem("math", "从5个球中无放回抽取2次", ("求概率",)),
        StructuredStem("math", stem.raw_text, ("求期望",)),
    ):
        assert not compare_critical_conditions(stem, other)[0]


def test_completeness_matches_questions_and_requires_explicit_finals():
    from app.application.commands.problem_solving import _parse_and_verify_route
    from app.contexts.problem_solving.domain.dossier import (
        DossierConfidencePolicy,
        StructuredStem,
    )

    stem = StructuredStem("math", "两问", ("第一问", "第二问"))
    check = DossierConfidencePolicy.evaluate_subproblem_completeness
    assert check(stem, {"第二问": "3", "备注": "代入"})["missing_subproblems"] == [
        "第一问"
    ]
    assert check(stem, {"(2)": "3", "(1)": "4"})["complete"]
    route = _good_math_route()
    del route["final_answers"]
    assert _parse_and_verify_route(None, route).final_answers == {}


@pytest.mark.parametrize("response", [None, {}, TimeoutError("read timed out")])
def test_missing_reread_terminates_once(staged, response):
    class Solver:
        reads = 0

        def extract_stem(self, *, independent_reread, **kwargs):
            if independent_reread:
                self.reads += 1
                if isinstance(response, Exception):
                    raise response
                return response
            return {
                "raw_text": "图片题",
                "needs_student_confirmation": True,
                "tier": "T1",
            }

    solver = Solver()
    with use_definitions(staged):
        result = _solve_for_mentor(
            content="图片题", images=["img"], solver=solver, bank_lookup=None
        )
    assert solver.reads == 1
    assert result.stem.needs_student_confirmation and result.status == "low_confidence"
    assert "reread_unavailable" in result.stem.disputed_conditions


@pytest.mark.parametrize("use_staged", [True, False])
def test_parallel_solver_keeps_fast_answer_before_deadline(staged, use_staged):
    import time
    from contextlib import nullcontext
    from threading import Event

    from app.application.commands.problem_solving import solve_and_verify_problem
    from app.contexts.problem_solving.domain.dossier import StructuredStem
    from app.infrastructure.ai.client import model_time_budget, remaining_model_time

    release = Event()

    class Solver:
        def solve_route(self, *, route_hint, **kwargs):
            if route_hint == "T2_algebraic":
                release.wait(1.5)
            return _good_math_route()

    try:
        with (
            use_definitions(staged) if use_staged else nullcontext(),
            model_time_budget(0.6),
        ):
            start = time.monotonic()
            result = solve_and_verify_problem(
                stem=StructuredStem("math", "求导"),
                solver=Solver(),
                math_engine=None,
                initial_tier="T2",
            )
            assert time.monotonic() - start < 0.6
            assert remaining_model_time() > 0
            assert result.evidence["route_count"] == 1
            assert result.evidence["timed_out_routes"] == ["T2_algebraic"]
            assert result.final_answers == {"(1)": "2*x"}
    finally:
        release.set()


@pytest.mark.parametrize(
    "timed_out", [{"T2_alternative"}, {"T2_algebraic", "T2_alternative"}]
)
def test_explicit_branch_deadline_returns_only_valid_candidates(staged, timed_out):
    from app.infrastructure.ai.errors import ModelTimeBudgetExceeded

    class Solver:
        def extract_stem(self, **kwargs):
            return {"tier": "T2", "raw_text": "求导", "subproblems": ["(1)"]}

        def solve_route(self, *, route_hint, **kwargs):
            if route_hint in timed_out:
                raise ModelTimeBudgetExceeded("branch deadline")
            return _good_math_route()

    with use_definitions(staged):
        result = _solve_for_mentor(
            content="求导", images=[], solver=Solver(), bank_lookup=None
        )
    assert set(result.evidence["timed_out_routes"]) == timed_out
    assert result.evidence["route_count"] == 2 - len(timed_out)
    if len(timed_out) == 2:
        assert result.status == "failed" and not result.final_answers
    else:
        assert result.confidence == "medium" and result.final_answers == {"(1)": "2*x"}


def test_upgraded_solver_and_mentor_budgets_and_discipline_prompts():
    from app.agent_specs.blueprint_steps import BACKUP, EXTRACT, PLANNER_ID
    from app.agent_specs.guardian_contracts import (
        MENTOR_EXPLAIN_ID,
        direct_mentor_workflow,
        provision_mentor_explain,
    )

    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    record = upgrade(add_blueprint(source, gaokao=True))
    files = record["bundle"]["files"]

    for uid in (PLANNER_ID, BACKUP):
        doc = files[f"agents/{uid}.json"]
        for model_cfg in doc["models"]:
            assert model_cfg["max_output_tokens"] >= 16384
            if model_cfg.get("enable_thinking"):
                assert model_cfg["thinking_budget"] <= 2560
                assert model_cfg["max_output_tokens"] > model_cfg["thinking_budget"]
        prompt = doc["prompt"]["template"]
        assert "[solver-discipline.v2]" in prompt
        assert "inspect_image" in prompt
        assert "纸带" in prompt

    assert "inspect_image" in files[f"agents/{EXTRACT}.json"]["prompt"]["template"]
    assert "选项" in files[f"agents/{EXTRACT}.json"]["prompt"]["template"]
    assert "臆测" in files[f"agents/{PLANNER_ID}.json"]["prompt"]["template"]

    files[f"agents/{MENTOR_EXPLAIN_ID}.json"] = provision_mentor_explain(
        model="qwen3.5-plus", enable_thinking=True, thinking_budget=4096
    )
    direct_mentor_workflow(files)
    mentor_doc = files[f"agents/{MENTOR_EXPLAIN_ID}.json"]
    assert mentor_doc["models"][0]["max_output_tokens"] >= 16384
    assert mentor_doc["models"][0]["thinking_budget"] <= 2560
    assert "[mentor-discipline.v2]" in mentor_doc["prompt"]["template"]
    assert "凝练交付原则" in mentor_doc["prompt"]["template"]

    turn_doc = files["agents/tutoring.turn.json"]
    def caps(doc):
        return [m["max_output_tokens"] for m in doc["models"]]
    assert caps(turn_doc) == caps(source["bundle"]["files"]["agents/tutoring.turn.json"])
    variant = upgrade(add_blueprint(source, gaokao=True), ward_max_output_tokens=8192)
    assert set(caps(variant["bundle"]["files"]["agents/tutoring.turn.json"])) == {8192}
    assert "[tutor-visual-discipline.v2]" in turn_doc["prompt"]["template"]
    assert "[tutor-visual-discipline.v1]" in turn_doc["prompt"]["template"]


def test_t1_primary_failure_automatically_falls_back_to_backup(staged):
    class Solver:
        def __init__(self):
            self.routes = []

        def extract_stem(self, **kwargs):
            return {"tier": "T1", "raw_text": "求 f(x)=x^2 的导数", "subproblems": ["(1)"]}

        def solve_route(self, *, route_hint, **kwargs):
            self.routes.append(route_hint)
            if route_hint == "T1":
                return None  # Simulates length_truncated / json_parse_error
            return _good_math_route()

    solver = Solver()
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = _solve_for_mentor(
            content="求 f(x)=x^2 的导数", images=[], solver=solver, bank_lookup=None
        )
    assert solver.routes == ["T1", "T1_backup"]
    assert res.status == "ready"
    assert res.final_answers == {"(1)": "2*x"}
    assert res.evidence.get("used_backup") is True
    nodes = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}]
    assert nodes == ["extract", "select", "ordinary", "verify", "backup", "verify_backup", "finish"]


def test_problem_solver_gateway_executes_inspect_image_and_science_tool_loop(staged, monkeypatch):
    from types import SimpleNamespace

    from app.agent_specs.image_refs import image_ref
    from app.application.ports.image_inspection import InspectImageResult
    from app.application.ports.math_engine import MathResult
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.contexts.problem_solving.domain.dossier import StructuredStem
    from app.infrastructure.ai import components

    fake_img = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA=="
    expected_ref = image_ref(fake_img)
    calls = []

    class FakeInspector:
        def inspect(self, req, *, authorized_images):
            assert req.image_ref == expected_ref
            assert expected_ref in authorized_images
            return InspectImageResult(
                status="unique",
                image_ref=req.image_ref,
                crop_ref="crop_01",
                label=req.label,
                crop_data_url="data:image/png;base64,iVBORw0KGgo=",
                width=200,
                height=120,
            )

    class FakeMathEngine:
        def execute(self, math_input):
            assert math_input.op == "evaluate"
            return MathResult(status="ok", result="2.485")

    responses = iter(
        [
            {
                "tool_request": {
                    "name": "inspect_image",
                    "args": {
                        "image_ref": expected_ref,
                        "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.6},
                        "label": "螺旋测微器放大",
                    },
                }
            },
            {
                "tool_request": {
                    "name": "science",
                    "args": {"op": "evaluate", "args": {"expression": "2 + 0.485"}},
                }
            },
            _good_math_route(),
        ]
    )

    def fake_completion(*, messages, **kwargs):
        calls.append(messages[-1]["content"])
        return components.ChatCompletionResult(
            raw=json.dumps(next(responses)), finish_reason="stop", stream_completed=True
        )

    # Keep the production parser and schema checks, with the provider transport stubbed.
    monkeypatch.setattr(components, "invoke_json_component", invoke_json_component)
    monkeypatch.setattr(components, "complete_json_chat", fake_completion)
    monkeypatch.setattr("app.infrastructure.ai.client.dashscope_client", lambda **kwargs: object())

    gateway = QwenProblemSolverGateway(
        settings_obj=SimpleNamespace(agent_model_timeout_seconds=30),
        math_engine=FakeMathEngine(),
        image_inspector=FakeInspector(),
    )
    with use_definitions(staged):
        out = gateway.solve_route(
            stem=StructuredStem("physics", "读出螺旋测微器示数"),
            images=[fake_img],
            route_hint="T1",
        )

    assert out == _good_math_route()
    assert len(calls) == 3
    # Second call receives inspected crop image part + observation
    second_call = calls[1]
    assert isinstance(second_call, list)
    assert any(
        part.get("type") == "image_url"
        and part["image_url"]["url"] == "data:image/png;base64,iVBORw0KGgo="
        for part in second_call
    )
    assert "crop_01" in second_call[0]["text"]
    # Third call receives science tool deterministic observation
    assert "2.485" in calls[2][0]["text"]


@pytest.mark.parametrize("unit_id", [
    "tutoring.stem-extract", "tutoring.stem-review", PLANNER_ID, BACKUP,
])
def test_blueprint_intermediate_and_final_contracts_are_distinct(staged, unit_id):
    from jsonschema import ValidationError

    from app.agent_specs.contracts import validate_output

    unit = staged.units[unit_id]
    request = {"name": "inspect_image", "args": {}}
    validate_output(unit, {"tool_request": request})
    for invalid in (
        {"tool_request": request, "subject": "physics"},
        {"tool_request": {"name": "unlisted", "args": {}}},
        {"tool_request": {"name": "inspect_image", "args": []}},
        {},
    ):
        with pytest.raises((ValueError, ValidationError)):
            validate_output(unit, invalid)


def test_tool_budget_cannot_turn_a_request_into_a_finished_stem(staged, monkeypatch):
    from app.application.ports.problem_solving import QwenProblemSolverGateway

    gateway = QwenProblemSolverGateway()
    monkeypatch.setattr(gateway, "MAX_TOOL_ROUNDS", 0)
    monkeypatch.setattr(
        gateway, "_invoke_once",
        lambda **kwargs: {"tool_request": {"name": "inspect_image", "args": {}}},
    )
    with use_definitions(staged):
        assert gateway.extract_stem(text="读图", images=[]) is None


def test_student_request_solve_binds_image_identity_and_worker_extracts_new_image_problem(staged, db):
    from app.application.commands.problem_solving import (
        ExecuteDossierSolveCommand,
        RequestSolveCommand,
    )
    from app.infrastructure.persistence.models import uid

    ward_id = uid()
    img_a = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA=="
    img_b = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAE/2wBDAA=="
    enqueued = []
    cmd = RequestSolveCommand(db, enqueue_fn=lambda did, imgs=None: enqueued.append((did, list(imgs or []))))

    d1 = cmd.execute(ward_id=ward_id, text="帮我看看", images=[img_a])
    d2 = cmd.execute(ward_id=ward_id, text="帮我看看", images=[img_b])
    d1_repeat = cmd.execute(ward_id=ward_id, text="帮我看看", images=[img_a])

    # Different images with identical generic text MUST NOT collide on the same dossier
    assert d1.dossier_id != d2.dossier_id
    assert d1_repeat.dossier_id == d1.dossier_id

    # Worker runs `extract` on unextracted student image dossier and upgrades to T2 when classified
    class Solver:
        def __init__(self):
            self.extracted = 0
            self.routes = []

        def extract_stem(self, *, independent_reread, **kwargs):
            self.extracted += 1
            return {
                "subject": "physics",
                "tier": "T2",
                "raw_text": "压轴计算题完整题面",
                "subproblems": ["(1)", "(2)"],
                "needs_student_confirmation": False,
            }

        def solve_route(self, *, route_hint, **kwargs):
            self.routes.append(route_hint)
            return _good_math_route()

    solver = Solver()
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        settled = ExecuteDossierSolveCommand(db, solver=solver).execute(
            dossier_id=d1.dossier_id, images=[img_a]
        )

    assert solver.extracted == 1
    assert set(solver.routes) == {"T2_algebraic", "T2_alternative"}
    assert settled.tier == "T2"
    assert settled.stem.subject == "physics"
    nodes = [e["node_id"].split(".")[-1] for e in trace.events if e["kind"] in {"agent", "gate", "action"}]
    assert nodes[0] == "extract"


@pytest.mark.parametrize("inline", [False, True])
def test_mentor_extract_crops_are_authorized_for_primary_only(staged, monkeypatch, inline):
    from app.agent_specs.blueprint_steps import EXTRACT
    from app.agent_specs.image_refs import image_ref
    from app.application.ports.image_inspection import InspectImageResult
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    source = "data:image/png;base64,YQ=="
    crop = "data:image/png;base64,Yg=="
    ref = image_ref(source)

    class Inspector:
        def inspect(self, request, *, authorized_images):
            assert authorized_images == {ref: source}
            return InspectImageResult(status="unique", image_ref=ref, crop_ref="crop_01",
                                      crop_data_url=crop, width=10, height=10)

    gateway = QwenProblemSolverGateway(guardian_request="读数", image_inspector=Inspector())
    args = {"image_ref": ref, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}, "label": "刻度"}
    extracted = {"tier": "T1", "subject": "physics", "shared_stem_summary": "读数"}
    extract_turns = ([{**extracted, "planner_crop": args}] if inline else
                     [{"tool_request": {"name": "inspect_image", "args": args}}, extracted])
    responses = iter([*extract_turns, {}, {}, {}, {}, {}])
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["user"])
        return next(responses)

    monkeypatch.setattr(gateway, "_invoke_once", complete)
    stem = StructuredStem("physics", "读数")
    monkeypatch.setattr(staged.units[EXTRACT].models[0], "guardian_crop_handoff", True)
    with use_definitions(staged):
        gateway.extract_stem(text="读数", images=[source])
        gateway.solve_route(stem=stem, images=[source], route_hint="T1")
        gateway.solve_route(stem=stem, images=[source], route_hint="T1_backup")
        gateway.solve_route(stem=stem, images=["data:image/png;base64,Yw=="], route_hint="T1")
        gateway.extract_stem(text="换题", images=[source])
        gateway.solve_route(stem=stem, images=[source], route_hint="T1")
    assert [crop in str(call) for call in calls] == [False, *([] if inline else [True]), True, False, False, False, False]


def test_select_gate_handles_worksheet_batch_short_circuit_and_pre_extracted_bank_lookup(staged):
    from app.application.commands.problem_solving import execute_blueprint
    from app.contexts.problem_solving.domain.dossier import (
        ProblemDossier,
        StructuredStem,
    )

    class WorksheetSolver:
        def __init__(self):
            self.solve_called = False

        def extract_stem(self, *, independent_reread, **kwargs):
            return {
                "subject": "math",
                "tier": "T0",
                "raw_text": "整页20道口算题",
                "subproblems": [],
                "needs_student_confirmation": False,
                "worksheet_batch": True,
            }

        def solve_route(self, **kwargs):
            self.solve_called = True
            return _good_math_route()

    ws_solver = WorksheetSolver()
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        res = execute_blueprint(
            stem=StructuredStem(subject="general", raw_text="帮我批改整页口算"),
            images=["img"],
            solver=ws_solver,
            math_engine=SubprocessMathEngineAdapter(),
            question="帮我批改整页口算",
        )
    assert ws_solver.solve_called is False
    assert res.status == "low_confidence"
    assert res.evidence["skipped_reason"] == "worksheet_batch"
    assert res.evidence["coverage"] == "skipped"
    assert any(
        e["kind"] == "edge" and e.get("condition_id") == "worksheet_batch" and e.get("selected") is True
        for e in trace.events
    )

    # Pre-extracted stem (START -> select) still runs centralized bank_lookup in select Gate
    from datetime import datetime, timezone

    from app.contexts.tutoring.domain.blueprint import Approach, Milestone

    cached = ProblemDossier.create_pending(
        dossier_id="d-bank-1",
        scope="bank",
        owner_ward_id=None,
        stem=StructuredStem(subject="math", raw_text="求 f(x)=x^2 导数", subproblems=("(1)",)),
        tier="T1",
        solver_version="test-v1",
        now_at=datetime.now(timezone.utc),
    ).complete_solve(
        approaches=(
            Approach(
                id="A1",
                name="求导法",
                milestones=(Milestone(id="M1", goal="求导", check_kind="symbolic_equivalence", canonical_target="2*x"),),
            ),
        ),
        invariants=(),
        scoring_points=(),
        final_answers={"(1)": "2*x"},
        confidence="high",
        tier="T1",
        evidence={},
    )

    class NeverSolve:
        def solve_route(self, **kwargs):
            raise AssertionError("bank hit in select should never call solve_route")

    trace2 = Recorder()
    with use_definitions(staged), trace2.capture():
        res2 = execute_blueprint(
            stem=cached.stem,
            images=[],
            solver=NeverSolve(),
            math_engine=SubprocessMathEngineAdapter(),
            question=None,
            bank_lookup=lambda *, stem: cached,
        )
    assert res2.status == "ready"
    assert res2.final_answers == {"(1)": "2*x"}
    assert [e["node_id"].split(".")[-1] for e in trace2.events if e["kind"] in {"agent", "gate", "action"}] == [
        "select", "finish"
    ]


def test_legacy_12_node_blueprint_snapshot_remains_compatible():
    from app.agent_specs import blueprint_steps as steps
    from app.agent_specs.admin_bundle import contract_compatibility

    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    record = upgrade(add_blueprint(source, gaokao=True))
    # Force legacy 12-node edges (single unconditional START -> extract, no worksheet_batch)
    record["bundle"]["files"][steps.FLOW_FILE] = steps.workflow(v2_edges=False)
    record["bundle"]["compatibility"] = contract_compatibility(record["bundle"]["files"])
    catalog = compile_bundle(record["bundle"]).catalog
    with use_definitions(catalog):
        assert load_catalog().spec(steps.WORKFLOW_ID).id == steps.WORKFLOW_ID


def test_text_only_extract_preserves_original_options_while_image_uses_transcription(staged, monkeypatch):
    from app.application.commands.problem_solving import execute_blueprint
    from app.application.ports.problem_solving import QwenProblemSolverGateway
    from app.contexts.problem_solving.domain.dossier import StructuredStem

    full_mcq = (
        "哺乳动物成熟红细胞的细胞膜含有丰富的水通道蛋白，硝酸银（AgNO3）可使水通道蛋白失去活性。"
        "下列叙述错误的是（　　）\n"
        "A. 经AgNO3处理的红细胞在低渗蔗糖溶液中会膨胀\n"
        "B. 经AgNO3处理的红细胞在高渗蔗糖溶液中不会变小\n"
        "C. 未经AgNO3处理的红细胞在低渗蔗糖溶液中会迅速膨胀\n"
        "D. 未经AgNO3处理的红细胞在高渗蔗糖溶液中会迅速变小"
    )
    truncated_summary = (
        "哺乳动物成熟红细胞的细胞膜含有丰富的水通道蛋白，硝酸银（AgNO3）可使水通道蛋白失去活性。"
        "下列叙述错误的是（　　）"
    )

    # 1. Gateway adapter: pure-text extract_stem must not overwrite raw_text with a truncated summary.
    gateway = QwenProblemSolverGateway()
    monkeypatch.setattr(
        gateway,
        "_invoke",
        lambda payload, images, **kwargs: {
            "subject": "biology",
            "shared_stem_summary": truncated_summary,
            "subproblems": [],
            "diagram_summary": "无图",
            "needs_student_confirmation": False,
            "tier": "T1",
        },
    )
    with use_definitions(staged):
        text_extracted = gateway.extract_stem(text=full_mcq, images=[])
        img_extracted = gateway.extract_stem(
            text="帮我解这道选择题", images=["data:image/png;base64,YQ=="]
        )

    assert text_extracted is not None
    assert text_extracted["subject"] == "biology"
    assert text_extracted["raw_text"] == full_mcq
    assert "B. 经AgNO3处理的红细胞在高渗蔗糖溶液中不会变小" in text_extracted["raw_text"]

    assert img_extracted is not None
    assert img_extracted["raw_text"] == truncated_summary

    # 2. Workflow orchestration: execute_blueprint passes full original text (with A-D) to solve_route.
    seen_stems: list[str] = []

    class TruncatingSolver:
        def extract_stem(self, *, text, images, independent_reread=False):
            return {
                "subject": "biology",
                "raw_text": truncated_summary,
                "subproblems": [],
                "needs_student_confirmation": False,
                "tier": "T1",
            }

        def solve_route(self, *, stem, images, route_hint, feedback=None):
            seen_stems.append(stem.raw_text)
            return {
                "subject": "biology",
                "final_answers": {"main": "B"},
                "approaches": [
                    {
                        "id": "A1",
                        "name": "逐项分析",
                        "milestones": [
                            {
                                "id": "M1",
                                "goal": "核对选项 B",
                                "check_kind": "conceptual_rubric",
                                "canonical_target": "B 错误",
                            }
                        ],
                    }
                ],
            }

    with use_definitions(staged):
        result = execute_blueprint(
            stem=StructuredStem(subject="general", raw_text=full_mcq),
            question=full_mcq,
            images=[],
            solver=TruncatingSolver(),
            math_engine=None,
        )

    assert result.stem.subject == "biology"
    assert result.stem.raw_text == full_mcq
    assert seen_stems == [full_mcq]
    assert result.final_answers == {"main": "B"}
