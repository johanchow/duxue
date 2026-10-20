"""图的出口检查：文字泄露仍整轮回退，图的任何问题只丢图。"""

import pytest

from app.application.workflows.tutor_loop import vet_candidate
from app.application.workflows.tutor_turn import TutorTurnCandidate
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from tests.support.fakes import StaticLeakJudge, StaticVisualLeakJudge, tutor_raw
from tests.unit.tutoring.test_tutor_visual import SEGMENT, STEPS, SVG

PROTECTED = TutorPermit(True, AttemptSummary())
OPEN = TutorPermit(False, AttemptSummary())


def vet(raw, judge, *, permit=PROTECTED):
    return vet_candidate(
        TutorTurnCandidate.model_validate(raw), permit=permit, leak_judge=judge,
        task_title="应用题", problem_summary="小明有3份，小红有5份，一共几份",
    )


def homework(**extra):
    return tutor_raw("guide", "先看看谁多谁少？", relation="same", visual=SEGMENT, **extra)


def test_homework_turn_keeps_a_diagram_that_both_judges_accept():
    judge = StaticVisualLeakJudge()
    result = vet(homework(), judge)
    assert result.failure is None and result.visual is not None and result.visual_dropped is None
    assert judge.calls == 1 and len(judge.visual_texts) == 1
    assert "合计未知" in judge.visual_texts[0]  # the judge sees unknown markers, not a guess


@pytest.mark.parametrize("visual_result", [True, None, RuntimeError("boom")])
def test_a_bad_diagram_verdict_drops_only_the_diagram(visual_result):
    result = vet(homework(), StaticVisualLeakJudge(visual_result=visual_result))
    assert result.failure is None  # the words are still shown
    assert result.verdict is not None and result.verdict.ok
    assert result.visual is None
    assert result.visual_dropped == ("visual_leak_detected" if visual_result is True else "visual_leak_check_failed")


@pytest.mark.parametrize("text_result,reason", [(True, "leak_detected"), (None, "leak_check_failed")])
def test_a_text_leak_still_falls_back_the_whole_turn(text_result, reason):
    result = vet(homework(), StaticVisualLeakJudge(result=text_result, visual_result=False))
    assert result.failure == reason and result.verdict is None


def test_a_judge_without_visual_support_fails_closed_for_the_diagram_only():
    result = vet(homework(), StaticLeakJudge(False))
    assert result.failure is None and result.visual is None
    assert result.visual_dropped == "visual_leak_check_failed"


def test_answer_marker_in_a_protected_diagram_drops_it_without_asking_the_judge():
    marker_visual = {**SEGMENT, "alt": f"{ANSWER_LEAK_MARKERS[0]} 8"}
    judge = StaticVisualLeakJudge()
    result = vet(tutor_raw("guide", "先看看谁多谁少？", relation="same", visual=marker_visual), judge)
    assert result.failure is None and result.visual is None
    assert result.visual_dropped == "visual_answer_marker"
    assert judge.visual_texts == []


def test_unprotected_knowledge_turn_needs_no_leak_judge_for_its_diagram():
    judge = StaticVisualLeakJudge(result=True, visual_result=True)  # would fail if consulted
    raw = tutor_raw("answer", "水会先蒸发再凝结。", relation="none", visual=STEPS)
    result = vet(raw, judge, permit=OPEN)
    assert result.failure is None and result.visual is not None
    assert judge.calls == 0 and judge.visual_texts == []


def test_invalid_diagram_is_dropped_and_reported_without_calling_the_judge():
    raw = tutor_raw("guide", "先看看谁多谁少？", relation="same", visual={**SEGMENT, "bars": []})
    judge = StaticVisualLeakJudge()
    result = vet(raw, judge)
    assert result.failure is None and result.visual is None
    assert result.visual_dropped == "visual_invalid"
    assert judge.calls == 1 and judge.visual_texts == []


def test_relation_none_on_a_protected_problem_is_still_checked_even_with_a_diagram():
    """非事实的回答在受保护的题上仍交判官；单个事实才跳过文字判官。"""
    raw = tutor_raw(
        "answer", "先把 3 移到右边再看。", relation="none", topic="spontaneous_curiosity", visual=STEPS,
    )
    result = vet(raw, StaticVisualLeakJudge(True, True), permit=PROTECTED)
    assert result.failure == "leak_detected"


def test_relation_none_without_a_protected_problem_is_not_checked_even_with_a_diagram():
    raw = tutor_raw("answer", "这个词是 in advance。", relation="none", visual=STEPS)
    result = vet(raw, StaticVisualLeakJudge(True, True), permit=OPEN)
    assert result.failure is None and result.visual is not None


def test_a_short_single_fact_still_needs_the_judge_on_a_protected_problem():
    """The model's fact label is not an authority to bypass protected-problem review."""
    for raw in (
        tutor_raw("answer", "beach。", relation="same", depth="recall"),
        tutor_raw("answer", "斜边是最长的边。", relation="same", depth="atomic"),
        tutor_raw("answer", "beach 是海滩。", relation="none", topic="atomic_lookup"),
        tutor_raw("answer", "beach 是海滩。", relation="none"),  # unknown topic is a lookup
    ):
        judge = StaticLeakJudge(False)
        assert vet(raw, judge).failure is None and judge.calls == 1, raw


def test_a_protected_choice_disguised_as_a_short_fact_still_needs_independent_review():
    raw = tutor_raw("answer", "选 B。", relation="same", depth="recall")
    judge = StaticLeakJudge(True)
    assert vet(raw, judge, permit=PROTECTED).failure == "leak_detected"
    assert judge.calls == 1


def test_the_fact_classifier_does_not_use_keywords_or_digits_to_bypass_review():
    """Even a short self-declared fact reaches the independent judge."""
    from app.application.workflows.tutor_loop import fact_gate

    for content in ("得数是 391。", "x＝y＋z", "选 B。", "这句话是错的。", "√", "所以是质数。"):
        raw = tutor_raw("answer", content, relation="same", depth="recall")
        assert fact_gate(TutorTurnCandidate.model_validate(raw)) is None
        judge = StaticLeakJudge(True)
        assert vet(raw, judge).failure == "leak_detected" and judge.calls == 1
    long = tutor_raw("answer", "海" * 121, relation="same", depth="recall")
    assert fact_gate(TutorTurnCandidate.model_validate(long)) == "too_long"
    judge = StaticLeakJudge(True)
    assert vet(long, judge).failure == "leak_detected" and judge.calls == 1


def test_the_gate_needs_a_fact_label_on_an_answer():
    from app.application.workflows.tutor_loop import FACT_REPLY_MAX_CHARS, fact_gate

    def gate(raw):
        return fact_gate(TutorTurnCandidate.model_validate(raw))

    assert FACT_REPLY_MAX_CHARS == 120
    assert gate(tutor_raw("answer", "海" * 120, relation="same", depth="atomic")) is None
    assert gate(tutor_raw("guide", "beach。", relation="same", depth="atomic")) is None
    assert gate(tutor_raw("answer", "beach。", relation="same")) == "not_fact"  # missing depth is reasoning
    assert gate(tutor_raw("answer", "因为散射。", relation="none", topic="spontaneous_curiosity")) == "not_fact"
    clarify = {"act": "clarify", "content": "哪一个？", "clarify": {"candidates": ["beach"]}}
    assert gate(clarify) == "not_fact"


def test_a_gated_fact_with_a_diagram_still_has_the_diagram_judged():
    raw = tutor_raw("answer", "beach 是海滩。", relation="none", visual=STEPS)
    judge = StaticVisualLeakJudge(False, True)
    result = vet(raw, judge)
    assert result.failure is None and result.visual is None and result.visual_dropped == "visual_leak_detected"
    assert judge.calls == 1 and len(judge.visual_texts) == 1


def test_answer_on_a_reasoning_problem_is_observed_not_rejected():
    result = vet(tutor_raw("answer", "先算总份数。", relation="same", depth="reasoning"), StaticLeakJudge())
    assert result.failure is None and "answer_on_reasoning" in result.shape_flags
    assert "answer_on_reasoning" not in vet(tutor_raw("guide", "先看看谁多？"), StaticLeakJudge()).shape_flags


def test_the_judge_reads_clarify_candidates_on_a_protected_problem():
    raw = {"act": "clarify", "content": "你问的是哪一个？", "clarify": {"candidates": ["一共 8 份", "小红多"]}}
    judge = StaticLeakJudge()
    assert vet(raw, judge).failure is None
    assert judge.texts == ["你问的是哪一个？\n一共 8 份\n小红多"]
    assert vet(raw, StaticLeakJudge(True)).failure == "leak_detected"
    assert vet(raw, StaticLeakJudge(None)).failure == "leak_check_failed"


def test_judge_problem_summary_lists_recent_problems_and_this_turn():
    from app.application.workflows.tutor_loop import (
        JUDGE_RECENT_PROBLEMS,
        judge_problem_summary,
    )

    assert judge_problem_summary([], "  ") is None
    assert judge_problem_summary([], "beach 什么意思") == "孩子本轮说：beach 什么意思"
    summary = judge_problem_summary(["新题：3+5", "旧题：小明有3份"], "上一题答案是多少")
    assert summary == "第1题：新题：3+5\n第2题：旧题：小明有3份\n孩子本轮说：上一题答案是多少"
    # 本轮的话就是最新那道题的摘要时不重复
    assert judge_problem_summary(["3+5=?"], "3+5=?") == "第1题：3+5=?"
    many = judge_problem_summary([f"题{i}" for i in range(10)], "")
    assert many.count("题：") == JUDGE_RECENT_PROBLEMS


def test_homework_turn_allows_svg_and_sends_inner_svg_text_to_visual_leak_judge():
    judge = StaticVisualLeakJudge()
    raw = tutor_raw("guide", "观察两条直角边。", relation="same", visual=SVG)
    result = vet(raw, judge)
    assert result.failure is None and result.visual is not None and result.visual.kind == "svg"
    assert len(judge.visual_texts) == 1
    assert "图内文字：直角三角形 | 3 | 4 | ?" in judge.visual_texts[0]

    # 若 SVG 内部 <text> 含答案标记，同样在不调判官时直接丢图
    leaked_svg = {
        **SVG,
        "svg": SVG["svg"].replace(">?<", f">{ANSWER_LEAK_MARKERS[0]} 5<"),
    }
    judge2 = StaticVisualLeakJudge()
    dropped = vet(tutor_raw("guide", "观察两条直角边。", relation="same", visual=leaked_svg), judge2)
    assert dropped.failure is None and dropped.visual is None
    assert dropped.visual_dropped == "visual_answer_marker"
    assert judge2.visual_texts == []
