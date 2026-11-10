import copy

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import read_snapshot
from app.agent_specs.definitions import use_definitions
from app.application.ports.math_engine import MathResult
from app.application.workflows.math_verification import MathClaim, MathVerification
from app.application.workflows.tutor_loop import run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
from math_executor.engine import execute
from scripts.upgrade_math_bundle import upgrade
from tests.support.fakes import StaticLeakJudge, tutor_raw


class Engine:
    def execute(self, request):
        return MathResult.model_validate(execute(request.model_dump()))


def test_ledger_rejects_forgery_reversal_wrong_step_and_cross_turn():
    ledger = MathVerification(Engine(), {"turn_id": "t1"}, set())
    record = ledger.run(
        {"op": "equivalent", "args": {"left": "90-37", "right": "53"}, "step_ref": "1"}
    )
    good = MathClaim(request_id=record["request_id"], step_ref="1", assertion="equal")
    ledger.validate([good])
    for claim in (
        good.model_copy(update={"request_id": "forged"}),
        good.model_copy(update={"step_ref": "2"}),
        good.model_copy(update={"assertion": "not_equal"}),
    ):
        with pytest.raises(ValueError):
            ledger.validate([claim])
    with pytest.raises(ValueError):
        MathVerification(Engine(), {"turn_id": "t2"}, set()).validate([good])
    with pytest.raises(ValueError):
        ledger.run(
            {"op": "evaluate", "args": {"expression": "1"}, "image_ref": "unauthorized"}
        )


def test_budget_and_unknown_never_authorize_a_verdict():
    ledger = MathVerification(None, {}, set())
    first = ledger.run({"op": "evaluate", "args": {"expression": "1"}})
    with pytest.raises(ValueError):
        ledger.validate([MathClaim(request_id=first["request_id"], assertion="equal")])
    for i in range(2, 9):
        ledger.run({"op": "evaluate", "args": {"expression": str(i)}})
    assert (
        ledger.run({"op": "evaluate", "args": {"expression": "9"}})["error_code"]
        == "resource_limit"
    )


def test_upgrade_is_explicit_compilable_and_preserves_models():
    record = read_snapshot()
    original = copy.deepcopy(record)
    upgraded = upgrade(record, enable=True)
    assert record == original
    compiled = compile_bundle(upgraded["bundle"])
    assert "tutoring.math" in compiled.catalog.units["tutoring.turn"].tools
    assert upgraded["kind"] == "draft"
    assert (
        upgraded["bundle"]["files"]["agents/tutoring.turn.json"]["models"]
        == record["bundle"]["files"]["agents/tutoring.turn.json"]["models"]
    )
    bad = copy.deepcopy(upgraded["bundle"])
    bad["files"]["gates/tutoring.leak-judge.json"]["prompt"]["template"] = "old prompt"
    with pytest.raises(ValueError, match="matching tutor and judge"):
        compile_bundle(bad)


class Judge(StaticLeakJudge):
    def __init__(self, math_ok):
        super().__init__(False)
        self.math_ok = math_ok
        self.math_contexts = []

    def check_math(self, *, text, context, images):
        self.math_contexts.append(context)
        return self.math_ok


class Model:
    def complete(self, **kwargs):
        records = [
            r
            for r in kwargs.get("observations", [])
            if r.get("tool") == "math" and r.get("request_id")
        ]
        if not records:
            return {
                "tool": "math",
                "args": {
                    "op": "equivalent",
                    "args": {"left": "90-37", "right": "53"},
                    "step_ref": "1",
                },
            }
        record = records[-1]
        return tutor_raw(
            content="这一步计算正确。",
            math_claims=[
                {
                    "request_id": record["request_id"],
                    "step_ref": "1",
                    "assertion": "equal",
                }
            ],
        )


@pytest.mark.parametrize("math_ok", [True, False, None])
def test_tool_loop_requires_independent_semantic_check(math_ok):
    bundle = upgrade(read_snapshot(), enable=True)["bundle"]
    compiled = compile_bundle(bundle)
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None,
            tutoring_session_id=None,
            problem=None,
            task_title=None,
            task_active=False,
            window=[],
            math_engine=Engine(),
        )
        judge = Judge(math_ok)
        result = run_tutor_turn(
            Model(),
            {"turn_id": "t"},
            "90-37=53对吗",
            [],
            [],
            tools,
            permit=TutorPermitPolicy.permit(None),
            leak_judge=judge,
            task_title=None,
            problem_summary="90-37=53",
        )
        assert judge.math_contexts
        assert len(tools.math_verification.records) == 1
        assert result.vetting is not None
        assert (result.vetting.failure is None) == (math_ok is True)


def test_math_gate_catches_omitted_claims_even_for_non_work():
    from tests.support.fakes import StaticTutorModel

    compiled = compile_bundle(upgrade(read_snapshot(), enable=True)["bundle"])
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None,
            tutoring_session_id=None,
            problem=None,
            task_title=None,
            task_active=False,
            window=[],
            math_engine=Engine(),
        )
        judge = Judge(False)
        result = run_tutor_turn(
            StaticTutorModel(
                tutor_raw(
                    act="answer",
                    relation="none",
                    topic="atomic_lookup",
                    content="90-37=54",
                )
            ),
            {},
            "帮我计算",
            [],
            [],
            tools,
            permit=TutorPermitPolicy.permit(None),
            leak_judge=judge,
            task_title=None,
            problem_summary=None,
        )
        assert judge.math_contexts and result.vetting.failure


def test_image_arithmetic_uses_same_ledger_and_preserves_uncertainty():
    from app.application.workflows.tutor_turn import TutorTurnCandidate

    ledger = MathVerification(Engine(), {"turn_id": "t"}, {"img_current"})
    report = {
        "conclusion": "all_correct",
        "coverage": "complete",
        "questions": [
            {
                "image_ref": "img_" + "a" * 24,
                "kind": "arithmetic",
                "location": "1",
                "task": "90-37",
                "student_answer": "53",
                "verdict": "correct",
                "basis": "模型自报",
                "calculation": {"expression": "90-37", "submitted": "53"},
            }
        ],
    }
    ledger.image_refs = {"img_" + "a" * 24}
    candidate = TutorTurnCandidate.model_validate(tutor_raw(image_review=report))
    verified = ledger.reconcile_image(candidate)
    assert len(verified.math_claims) == 1
    ledger.validate(verified.math_claims)
    assert len(ledger.records) == 1
    unavailable = MathVerification(None, {}, ledger.image_refs).reconcile_image(
        candidate
    )
    assert unavailable.image_review.conclusion == "uncertain"
    assert unavailable.image_review.questions[0].verdict == "uncertain"


def test_math_failure_does_not_commit_teaching_facts(db):
    from app.application.workflows.tutoring_workflow import TutoringWorkflow
    from app.infrastructure.persistence.models import OutboxEvent, TutoringProblem
    from tests.application.study.test_tutoring_workflow_usecase import _ask, _setup

    compiled = compile_bundle(upgrade(read_snapshot(), enable=True)["bundle"])
    with use_definitions(compiled.catalog):
        _, session = _setup(db)
        workflow = TutoringWorkflow(
            db, turn_model=Model(), leak_judge=Judge(False), math_engine=Engine()
        )
        outcome = _ask(db, workflow, session, "90-37=53对吗")
        assert outcome.next_interaction["model_fallback"] is True
        assert db.query(TutoringProblem).count() == 0
        assert db.query(OutboxEvent).count() == 0


def test_math_disagreement_repairs_once_without_backup():
    compiled = compile_bundle(upgrade(read_snapshot(), enable=True)["bundle"])
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(
            None,
            tutoring_session_id=None,
            problem=None,
            task_title=None,
            task_active=False,
            window=[],
            math_engine=Engine(),
        )
        judge = Judge(False)

        class NeverCall:
            def complete(self, **kwargs):
                raise AssertionError("math disagreement must not try a second repair")

        result = run_tutor_turn(
            Model(),
            {},
            "90-37=53",
            [],
            [],
            tools,
            permit=TutorPermitPolicy.permit(None),
            leak_judge=judge,
            backup_model=NeverCall(),
            task_title=None,
            problem_summary="90-37=53",
        )
        assert len(judge.math_contexts) == 2
        assert result.vetting.failure


def test_image_fraction_answer_passes_actual_candidate_pipeline():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import call_tutor_model
    from tests.support.fakes import StaticTutorModel
    pixels = 'data:image/jpeg;base64,YQ=='
    compiled = compile_bundle(upgrade(read_snapshot(), enable=True)['bundle'])
    with use_definitions(compiled.catalog):
        tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None,
                             task_active=False, window=[], math_engine=Engine())
        tools.begin_math({'turn_id':'t'}, '检查分数', [pixels])
        report = {'conclusion':'all_correct','coverage':'complete','questions':[
            {'image_ref':image_ref(pixels),'kind':'arithmetic','location':'1','task':'1/3+1/6',
             'student_answer':'1/2','verdict':'correct','basis':'核算',
             'calculation':{'expression':'1/3+1/6','submitted':'1/2'}}]}
        result = call_tutor_model(StaticTutorModel(tutor_raw(image_review=report)), {}, '检查分数', [], [pixels], tools)
        assert result.failure is None
        assert result.candidate.image_review.questions[0].verdict == 'correct'
        assert result.candidate.math_claims[0].assertion == 'equal'
