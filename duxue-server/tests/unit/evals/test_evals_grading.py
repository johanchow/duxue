"""Grading goes through the production loop and exit checks, so the real incidents reproduce."""

import pytest

from app.infrastructure.ai.errors import ModelGatewayError
from evals.runner import Backends, run_sample
from evals.schema import EvalCase
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

LESSON = {
    "source_text": "kling beach 13:00", "locale": "en-US", "introduction": "我们来读这一句。",
    "reading_guide": "kling 读 /klɪŋ/，beach 读 /biːtʃ/。", "notes": [],
}
HISTORY = [
    {"author": "ward", "text": "最后一排的英文是什么句子？"},
    {"author": "companion", "text": "Return to Bali at 16:30"},
]


def _case(expect=None, component="tutoring.turn", **fields) -> EvalCase:
    base = {
        "id": "turn-test-00", "component": component, "conversation_id": "abc12345", "turn_index": 0,
        "student_said": "是的，是的。", "history": HISTORY, "source": "real", "label_status": "proposed",
        "expect": {"outcome_in": ["pronounce"], "lesson_source_contains_any": ["kling beach"]}
        if expect is None else expect,
    }
    return EvalCase.model_validate({**base, **fields})


def _sample(case, *raws, judge=None, **backend):
    backends = Backends(tutor_model=StaticTutorModel(*raws), leak_judge=judge or StaticLeakJudge(False), **backend)
    window = [{"author": r.author, "text": r.text} for r in case.history]
    return run_sample(case, backends, window, [])


def test_valid_pronounce_passes():
    raw = tutor_raw(act="pronounce", question_kind="knowledge_lookup", content="读 kling beach。", lesson=LESSON,
                    is_assignment_content=False)
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "pronounce"
    assert sample.observation.lesson_source == "kling beach 13:00"
    assert sample.passed


def test_confirm_without_solved_is_the_fallback_that_ward_saw():
    """2026-10-11: 「是的，是的」→ act=confirm, progress=some → whole turn fell back."""
    raw = tutor_raw(act="confirm", question_kind="chat", progress="some", content="确认一下：你问的是第四行，对吗？",
                    history_ref="u1", is_assignment_content=False)
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "fallback"
    assert sample.observation.reason == "confirm_without_solved"
    assert not sample.passed
    assert "confirm_without_solved" in sample.failures[0]


def test_clarify_instead_of_pronounce_fails_a_pronounce_case_but_is_not_a_fallback():
    raw = tutor_raw(act="clarify", question_kind="chat", content="你问的是哪一行？", candidates=["kling beach 13:00"],
                    is_assignment_content=False)
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "clarify"
    assert sample.observation.candidates == ["kling beach 13:00"]
    assert not sample.passed


def test_misplaced_question_kind_pronounce_is_recovered_like_production():
    raw = {"act": "pronounce", "question_kind": "pronounce", "content": "读 kling beach。", "lesson": LESSON}
    assert _sample(_case(), raw).observation.outcome == "pronounce"


def test_pronounce_without_lesson_falls_back_with_its_reason():
    raw = tutor_raw(act="pronounce", question_kind="chat", content="读一下。", lesson=None, is_assignment_content=False)
    sample = _sample(_case(), raw)
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "pronounce_without_lesson")


def test_lesson_for_the_wrong_sentence_fails_on_source_text():
    other = {**LESSON, "source_text": "diamond beach 10:00"}
    raw = tutor_raw(act="pronounce", question_kind="chat", content="读。", lesson=other, is_assignment_content=False)
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "pronounce"
    assert not sample.passed and "lesson_source" in sample.failures[0]


def test_provider_error_is_a_fallback_with_a_category_not_content():
    class Failing:
        def complete(self, **_):
            raise ModelGatewayError("model_transport_error")

    sample = run_sample(_case(), Backends(tutor_model=Failing(), leak_judge=StaticLeakJudge(False)), [], [])
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "model_transport_error")


def test_structure_error_gets_one_repair_then_falls_back():
    bad = {"act": "teleport", "content": "x"}
    sample = _sample(_case(), bad, bad)
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "invalid_model_candidate")


def test_unexpected_fallback_is_always_a_failure_even_without_expectations():
    case = _case(expect={})
    assert any("forbidden" in f for f in _sample(case, {"act": "x"}, {"act": "x"}).failures)


def test_knowledge_answer_passes_an_answer_case():
    case = _case(expect={"outcome_in": ["answer"], "content_contains_any": ["return to bali"]}, history=[],
                 student_said="最后一排的英文是什么句子？")
    raw = tutor_raw(act="answer", question_kind="knowledge_lookup", content="是 **Return to Bali at 16:30**。",
                    is_assignment_content=False, same_problem=False)
    assert _sample(case, raw).passed


GUARD = {
    "outcome_not_in": ["fallback", "answer"], "content_not_contains": ["x = 4"],
}
HOMEWORK = {"problem": {"summary": "2x + 3 = 11"}, "task_title": "数学作业", "task_active": True}


def test_guard_case_catches_an_answer_the_exit_checks_let_through():
    """The production exit passes this (marker list + a judge that said no); the case still fails it."""
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    reveal = tutor_raw(act="hint", question_kind="work_product_help", content="先移项：x = 4", reveals_solution=False)
    sample = _sample(case, reveal)
    assert sample.observation.outcome == "hint_like"
    assert not sample.passed and "forbidden text" in sample.failures[0]


def test_guard_case_fails_when_the_model_declares_a_reveal():
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    reveal = tutor_raw(act="answer", question_kind="work_product_help", content="答案出来了", reveals_solution=True)
    sample = _sample(case, reveal)
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "reveals_protected_work_product")
    assert not sample.passed


def test_guard_case_passes_on_a_hint_and_uses_the_leak_judge():
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    hint = tutor_raw(act="hint", question_kind="work_product_help", content="先想想：把 3 移到右边会怎样？")
    assert _sample(case, hint).passed
    judge = StaticLeakJudge(True)
    sample = _sample(case, hint, judge=judge)
    assert judge.calls == 1
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "leak_detected")


@pytest.mark.parametrize("label, expected_ok", [("tutoring", True), ("unclear", False)])
def test_intent_case(label, expected_ok):
    case = _case(component="companion.intent", expect={"intent_in": ["tutoring"]}, student_said="为什么会有打雷？",
                 history=[])
    def complete(**_):
        return f'{{"intent": "{label}"}}'

    sample = run_sample(case, Backends(intent_complete=complete), [], [])
    assert sample.observation.outcome == label
    assert sample.passed is expected_ok


def test_intent_provider_error_is_visible_not_a_quiet_unclear():
    """2026-10-10: a 404 turned every turn into 「unclear」. The evaluation must say it was an error."""
    def broken(**_):
        raise ModelGatewayError("model_transport_error")

    case = _case(component="companion.intent", expect={"intent_in": ["unclear"]}, student_said="嗯", history=[])
    sample = run_sample(case, Backends(intent_complete=broken), [], [])
    assert sample.observation.outcome == "unclear"
    assert sample.observation.error == "model_transport_error"
    assert not sample.passed
