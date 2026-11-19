import json
from pathlib import Path

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.blueprint_steps import BACKUP, PLANNER_ID
from app.agent_specs.catalog import load_catalog
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.application.workflows.guardian_mentor import _solve_for_mentor
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
    assert trace.events[0]["node_id"] == "tutoring-blueprint.select"


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
