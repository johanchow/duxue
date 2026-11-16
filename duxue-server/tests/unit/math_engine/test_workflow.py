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
    judge_tpl = upgraded["bundle"]["files"]["gates/tutoring.leak-judge.json"]["prompt"]["template"]
    assert '"math_consistent":true或false或null' in judge_tpl
    assert "字段沿用既有契约，不加字段。" not in judge_tpl
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


def test_transient_unavailable_is_not_cached_and_failure_codes_are_decoupled():
    from tests.support.fakes import StaticTutorModel

    flaky_calls = 0

    class FlakyEngine:
        def execute(self, request):
            nonlocal flaky_calls
            flaky_calls += 1
            if flaky_calls == 1:
                return MathResult(status="unknown", error_code="unavailable")
            return MathResult.model_validate(execute(request.model_dump()))

    ledger = MathVerification(FlakyEngine(), {"turn_id": "t"}, set())
    first = ledger.run({"op": "equivalent", "args": {"left": "6*7", "right": "42"}})
    second = ledger.run({"op": "equivalent", "args": {"left": "6*7", "right": "42"}})
    assert first["error_code"] == "unavailable"
    assert second["status"] == "ok" and second["verdict"] == "equal"
    assert flaky_calls == 2

    compiled = compile_bundle(
        upgrade(
            read_snapshot(),
            enable=True,
            enable_thinking=True,
            thinking_budget=4096,
            judge_thinking_budget=1024,
        )["bundle"]
    )
    assert compiled.catalog.units["tutoring.turn"].models[0].enable_thinking is True
    assert compiled.catalog.units["tutoring.turn"].models[0].thinking_budget == 4096
    assert compiled.catalog.units["tutoring.turn"].models[1].enable_thinking is False
    assert compiled.catalog.units["tutoring.leak-judge"].models[0].thinking_budget == 1024

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
        bad_math = run_tutor_turn(
            Model(),
            {"turn_id": "t1"},
            "90-37=53对吗",
            [],
            [],
            tools,
            permit=TutorPermitPolicy.permit(None),
            leak_judge=Judge(False),
            task_title=None,
            problem_summary="90-37=53",
        )
        assert bad_math.vetting.failure == "math_inconsistent"

        outage = run_tutor_turn(
            Model(),
            {"turn_id": "t2"},
            "90-37=53对吗",
            [],
            [],
            TutorToolbox(
                None,
                tutoring_session_id=None,
                problem=None,
                task_title=None,
                task_active=False,
                window=[],
                math_engine=Engine(),
            ),
            permit=TutorPermitPolicy.permit(None),
            leak_judge=Judge(None),
            task_title=None,
            problem_summary="90-37=53",
        )
        assert outage.vetting.failure == "math_check_failed"

        pronounce_judge = Judge(False)
        pronounce_raw = {
            "act": "pronounce",
            "content": "**apple** 是苹果。",
            "pronounce": {
                "lesson": {
                    "source_text": "apple",
                    "locale": "en-US",
                    "introduction": "apple",
                    "reading_guide": "/ˈæp.əl/",
                    "notes": [],
                }
            },
        }
        pron = run_tutor_turn(
            StaticTutorModel(pronounce_raw),
            {"turn_id": "t3"},
            "apple怎么读",
            [],
            [],
            TutorToolbox(
                None,
                tutoring_session_id=None,
                problem=None,
                task_title=None,
                task_active=False,
                window=[],
                math_engine=Engine(),
            ),
            permit=TutorPermitPolicy.permit(None),
            leak_judge=pronounce_judge,
            task_title=None,
            problem_summary=None,
        )
        assert pron.vetting.failure is None
        assert pronounce_judge.math_contexts == []


def test_ward_grade_stage_reaches_tutoring_context_envelope(db):
    from app.application.workflows.tutoring_workflow import TutoringWorkflow
    from tests.application.study.test_tutoring_workflow_usecase import _ask
    from tests.support.factories import create_study_session, create_task, create_ward
    from tests.support.fakes import StaticTutorModel

    ward = create_ward(db, grade_stage="high")
    session = create_study_session(
        db, ward=ward, task=create_task(db, ward=ward, title="高三导数")
    )
    db.commit()
    model = StaticTutorModel(tutor_raw(content="先求定义域与导函数。"))
    workflow = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge(False))
    outcome = _ask(db, workflow, session, "讨论单调性")
    assert model.calls[0]["envelope"]["actor"]["grade_stage"] == "high"
    assert "grade_stage" not in outcome.context_snapshot["actor"]


def test_not_checking_placeholder_reply_triggers_response_phase():
    from app.agent_specs.image_refs import image_ref
    from tests.support.fakes import StaticTutorModel

    pixels = "data:image/jpeg;base64,YQ=="
    first = tutor_raw(
        content="待核验",
        image_review={
            "conclusion": "not_checking",
            "scope": "specified",
            "coverage": "complete",
            "questions": [],
        },
    )
    second = tutor_raw(content="先把球心距、截面圆半径和球半径画成一个直角三角形。")
    model = StaticTutorModel(first, second)
    judge = Judge(True)
    result = run_tutor_turn(
        model,
        {"turn_id": "t-placeholder"},
        "我不知道如何开始，请给我一个起步提示",
        [],
        [pixels],
        TutorToolbox(
            None,
            tutoring_session_id=None,
            problem=None,
            task_title=None,
            task_active=False,
            window=[],
            math_engine=Engine(),
        ),
        permit=TutorPermitPolicy.permit(None),
        leak_judge=judge,
        task_title=None,
        problem_summary='{"current_request":"球体截面问题"}',
        judge_images=[pixels],
    )
    assert result.vetting.failure is None
    assert result.call.candidate.content == "先把球心距、截面圆半径和球半径画成一个直角三角形。"
    assert model.calls[1]["envelope"]["image_review_phase"] == "response"
    assert image_ref(pixels) not in (result.call.candidate.content or "")


def test_phase3_upgrade_enables_reasoned_choice_and_partial_schema():
    upgraded = upgrade(read_snapshot(), enable=True, phase3=True)
    compiled = compile_bundle(upgraded["bundle"])
    turn_tpl = compiled.catalog.units["tutoring.turn"].prompt.template
    judge_tpl = compiled.catalog.units["tutoring.leak-judge"].prompt.template
    assert "[reasoned-choice.v1]" in turn_tpl
    assert "[reasoned-choice.v1]" in judge_tpl
    assert '"partial"' in judge_tpl
