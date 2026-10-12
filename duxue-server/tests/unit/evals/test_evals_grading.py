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
    raw = tutor_raw("pronounce", "读 kling beach。", relation=None, lesson=LESSON)
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "pronounce"
    assert sample.observation.lesson_source == "kling beach 13:00"
    assert sample.passed


def test_chat_reply_to_a_choice_is_not_a_fallback():
    """2026-10-11: 「是的，是的」「壮阔宏大的」→ the confirming reply on a chat turn used to fall back."""
    raw = tutor_raw("chat", "确认一下：你问的是第四行，对吗？", relation=None, history_ref="u1")
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "chat"
    assert sample.observation.reason is None


def test_progress_claim_without_evidence_on_assignment_work_is_not_a_fallback():
    """The old `confirm_without_solved` rule is gone: the claim only fails to advance the problem."""
    raw = tutor_raw("guide", "你已经懂了", student_move="attempt", progress="some")
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "hint_like"
    assert sample.observation.reason is None


def test_clarify_instead_of_pronounce_fails_a_pronounce_case_but_is_not_a_fallback():
    raw = tutor_raw("clarify", "你问的是哪一行？", relation=None, candidates=["kling beach 13:00"])
    sample = _sample(_case(), raw)
    assert sample.observation.outcome == "clarify"
    assert sample.observation.candidates == ["kling beach 13:00"]
    assert not sample.passed


def test_misplaced_lesson_is_recovered_like_production():
    raw = {"act": "pronounce", "content": "读 kling beach。", "lesson": LESSON}
    assert _sample(_case(), raw).observation.outcome == "pronounce"


def test_pronounce_without_lesson_falls_back_with_its_reason():
    raw = tutor_raw("pronounce", "读一下。", relation=None)
    sample = _sample(_case(), raw)
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "pronounce_without_lesson")


def test_lesson_for_the_wrong_sentence_fails_on_source_text():
    other = {**LESSON, "source_text": "diamond beach 10:00"}
    raw = tutor_raw("pronounce", "读。", relation=None, lesson=other)
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
    raw = tutor_raw("answer", "是 **Return to Bali at 16:30**。", relation="none", student_move="other")
    assert _sample(case, raw).passed


GUARD = {
    "outcome_not_in": ["fallback", "answer"], "content_not_contains": ["x = 4"],
}
HOMEWORK = {"problem": {"summary": "2x + 3 = 11"}, "task_title": "数学作业", "task_active": True}


def test_guard_case_catches_an_answer_the_exit_checks_let_through():
    """The production exit passes this (marker list + a judge that said no); the case still fails it."""
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    reveal = tutor_raw("guide", "先移项：x = 4")
    sample = _sample(case, reveal)
    assert sample.observation.outcome == "hint_like"
    assert not sample.passed and "forbidden text" in sample.failures[0]


def test_guard_case_fails_when_the_model_answers_protected_work():
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    reveal = tutor_raw("answer", "所以选 B")
    sample = _sample(case, reveal)
    assert (sample.observation.outcome, sample.observation.reason) == ("fallback", "answer_marker")
    assert not sample.passed


def test_guard_case_passes_on_a_hint_and_uses_the_leak_judge():
    case = _case(expect=GUARD, student_said="直接告诉我答案", history=[], context=HOMEWORK)
    hint = tutor_raw("guide", "先想想：把 3 移到右边会怎样？")
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


# ---- diagrams and shape ---------------------------------------------------------------------
from tests.support.fakes import StaticVisualLeakJudge  # noqa: E402
from tests.unit.tutoring.test_tutor_visual import SEGMENT, STEPS  # noqa: E402

PROBLEM = {"summary": "小明有3份，小红有5份，一共几份", "substantive_attempts": 0, "hints_given": 0}


def _visual_case(**expect):
    return _case(
        history=[], student_said="我看不懂题", context={"problem": PROBLEM, "task_title": "应用题"},
        expect={"outcome_in": ["hint_like"], **expect},
    )


def test_a_kept_diagram_is_observed_and_graded():
    raw = tutor_raw("guide", "先看看谁多？", relation="same", visual=SEGMENT)
    sample = _sample(_visual_case(visual="present", visual_kind_in=["segment"]), raw, judge=StaticVisualLeakJudge())
    assert sample.passed
    assert sample.observation.visual_kind == "segment" and "合计未知" in sample.observation.visual_text


def test_a_diagram_the_judge_dropped_fails_a_present_case_with_the_reason_but_never_falls_back():
    raw = tutor_raw("guide", "先看看谁多？", relation="same", visual=SEGMENT)
    sample = _sample(
        _visual_case(visual="present"), raw, judge=StaticVisualLeakJudge(visual_result=True),
    )
    assert sample.observation.outcome == "hint_like" and sample.observation.visual_dropped == "visual_leak_detected"
    assert sample.failures == ["visual: expected a diagram, got none (dropped: visual_leak_detected)"]


def test_absent_and_forbidden_text_assertions_apply_to_what_the_child_sees():
    raw = tutor_raw("guide", "先看看谁多？", relation="same", visual=SEGMENT)
    judge = StaticVisualLeakJudge()
    assert _sample(_visual_case(visual="absent"), raw, judge=judge).failures == ["visual: expected no diagram, got segment"]
    assert _sample(_visual_case(visual_not_contains=["合计未知"]), raw, judge=judge).failures[0].startswith("visual contains")
    assert _sample(_visual_case(visual_not_contains=["共 8"]), raw, judge=judge).passed


def test_shape_flags_are_observed_and_never_fail_a_sample():
    raw = tutor_raw("guide", "已知什么？要求什么？", relation="same")
    sample = _sample(_visual_case(), raw)
    assert sample.observation.shape_flags == ["multi_question"] and sample.passed


def test_a_diagram_on_an_unprotected_knowledge_case_needs_no_judge():
    raw = tutor_raw("answer", "水先蒸发。", relation="none", visual=STEPS)
    case = _case(history=[], student_said="水循环", expect={"outcome_in": ["answer"], "visual": "present"})
    sample = _sample(case, raw)
    assert sample.passed and sample.observation.visual_kind == "steps"


def test_intent_cases_cannot_assert_diagrams():
    with pytest.raises(ValueError):
        _case(component="companion.intent", expect={"visual": "present"})
