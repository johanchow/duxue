"""图的出口检查：文字泄露仍整轮回退，图的任何问题只丢图。"""

import pytest

from app.application.workflows.tutor_loop import vet_candidate
from app.application.workflows.tutor_turn import TutorTurnCandidate
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from tests.support.fakes import StaticLeakJudge, StaticVisualLeakJudge, tutor_raw
from tests.unit.tutoring.test_tutor_visual import SEGMENT, STEPS

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
    raw = tutor_raw("answer", "这个词是 in advance。", relation="none", visual=STEPS)
    result = vet(raw, StaticVisualLeakJudge(True, True), permit=PROTECTED)
    assert result.failure == "leak_detected"


def test_relation_none_without_a_protected_problem_is_not_checked_even_with_a_diagram():
    raw = tutor_raw("answer", "这个词是 in advance。", relation="none", visual=STEPS)
    result = vet(raw, StaticVisualLeakJudge(True, True), permit=OPEN)
    assert result.failure is None and result.visual is not None


def test_the_judge_is_told_the_depth_only_for_a_short_single_fact():
    from app.application.workflows.tutor_loop import FACT_REPLY_MAX_CHARS

    def depths(raw):
        judge = StaticLeakJudge()
        vet(raw, judge)
        return judge.depths

    assert depths(tutor_raw("answer", "beach。", relation="same", depth="recall")) == ["recall"]
    assert depths(tutor_raw("answer", "斜边是最长的边。", relation="same", depth="atomic")) == ["atomic"]
    assert depths(tutor_raw("answer", "x" * (FACT_REPLY_MAX_CHARS + 1), relation="same", depth="atomic")) == [None]
    # 非作业的一次性查询同样是单个事实；好奇心和模糊的 topic 不算
    assert depths(tutor_raw("answer", "beach。", relation="none", topic="atomic_lookup")) == ["atomic"]
    assert depths(tutor_raw("answer", "beach。", relation="none")) == ["atomic"]
    assert depths(tutor_raw("answer", "因为散射。", relation="none", topic="spontaneous_curiosity")) == [None]
    assert depths(tutor_raw("guide", "先看看谁多？", relation="same", depth="reasoning")) == [None]
    assert depths(tutor_raw("guide", "先看看谁多？", relation="same")) == [None]
    # guide 自称单个事实是标签矛盾：不放宽判官
    assert depths(tutor_raw("guide", "beach。", relation="same", depth="atomic")) == [None]


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
    from app.application.workflows.tutor_loop import JUDGE_RECENT_PROBLEMS, judge_problem_summary

    assert judge_problem_summary([], "  ") is None
    assert judge_problem_summary([], "beach 什么意思") == "孩子本轮说：beach 什么意思"
    summary = judge_problem_summary(["新题：3+5", "旧题：小明有3份"], "上一题答案是多少")
    assert summary == "第1题：新题：3+5\n第2题：旧题：小明有3份\n孩子本轮说：上一题答案是多少"
    # 本轮的话就是最新那道题的摘要时不重复
    assert judge_problem_summary(["3+5=?"], "3+5=?") == "第1题：3+5=?"
    many = judge_problem_summary([f"题{i}" for i in range(10)], "")
    assert many.count("题：") == JUDGE_RECENT_PROBLEMS
