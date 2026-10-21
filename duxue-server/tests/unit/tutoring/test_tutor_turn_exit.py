import pytest
from pydantic import ValidationError

from app.application.workflows.tutor_turn import TutorTurnCandidate, check_authority
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from tests.support.fakes import tutor_raw

PERMIT = TutorPermit(False, AttemptSummary())
LESSON = {
    "source_text": "in advance", "locale": "en-US",
    "introduction": "我们来一起读这个短语，它表示‘提前’的意思。",
    "reading_guide": "注意重音在第一个音节：in *a*dvance。",
    "notes": [
        {"kind": "stress", "segment": "in", "explanation": "in 是轻读音节，不强调。"},
        {"kind": "stress", "segment": "advance", "explanation": "advance 的重音在第一个音节。"},
    ],
}


def _verdict(raw: dict, *, permit=PERMIT):
    return check_authority(TutorTurnCandidate.model_validate(raw), permit)


def test_blank_optional_fields_are_absent_and_do_not_fail_a_knowledge_reply():
    """空字符串不是小目标。知识问答不能因此整轮回退。"""
    raw = tutor_raw(
        "answer", "提前用英语是 *in advance*。", relation="none", student_move="request_answer",
        progress="none", evidence="", next_subgoal="   ",
    )
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.next_subgoal is None
    assert candidate.subgoal_evidence is None
    verdict = _verdict(raw)
    assert verdict.ok
    assert verdict.effective_work_product is False


def test_a_next_subgoal_outside_work_is_ignored_not_rejected():
    """元数据与作业关系不一致只是不推进题目，不替换可展示的回答。"""
    raw = tutor_raw("answer", "这个词是 in advance。", relation="none", next_subgoal="写出第一个等式")
    assert _verdict(raw).ok


def test_pronounce_does_not_need_work():
    """发音卡不使用 work。不填 work 不能把完整的读法整轮丢掉。"""
    raw = {"act": "pronounce", "content": "‘in advance’ 读作 /ɪn ədˈvæns/。", "pronounce": {"lesson": LESSON}}
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.relation == "none"
    assert _verdict(raw).ok
    assert candidate.lesson is not None
    assert candidate.lesson.source_text == "in advance"


def test_flat_pronounce_fields_become_a_lesson():
    """模型常把发音字段摊在最外层。收成 lesson 后才能投影发音卡。"""
    raw = {
        "act": "pronounce",
        "content": "单词 **shoe** 的发音是 /ʃuː/。",
        "locale": "en-US",
        "source_text": "shoe",
        "introduction": "我们来一起读一读这个单词：shoe。",
        "reading_guide": "注意 sh 发 /ʃ/，oe 发 /uː/。",
        "notes": [{"kind": "linking", "explanation": "shoe 读成一个音节。", "segment": "shoe"}],
    }
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.lesson is not None
    assert candidate.lesson.source_text == "shoe"
    assert candidate.lesson.locale == "en-US"
    assert _verdict(raw).ok


def test_pronounce_without_a_lesson_is_rejected():
    verdict = _verdict({"act": "pronounce", "content": "读一下。"})
    assert not verdict.ok
    assert verdict.reason == "pronounce_without_lesson"


def test_pronounce_supports_multiple_lessons_and_checks_each_item():
    second = {
        "source_text": "also", "locale": "en-US",
        "introduction": "also（也）", "reading_guide": "al 发 /ɔːl/，so 发 /soʊ/。",
        "notes": [{"kind": "stress", "segment": "al", "explanation": "重音在第一音节。"}],
    }
    raw = {
        "act": "pronounce",
        "content": "这两个词的意思是：in advance（提前）、also（也）。",
        "pronounce": {"lessons": [LESSON, second]},
    }
    candidate = TutorTurnCandidate.model_validate(raw)
    assert [item.source_text for item in candidate.lessons] == ["in advance", "also"]
    assert candidate.lesson.source_text == "in advance"
    assert _verdict(raw).ok

    bad_second = {**second, "notes": [{"kind": "stress", "segment": "missing", "explanation": "不在原文里。"}]}
    bad_raw = {**raw, "pronounce": {"lessons": [LESSON, bad_second]}}
    assert _verdict(bad_raw).reason == "segment_not_in_source"


def test_clarify_discards_a_malformed_stray_lesson():
    """不明指代时，坏掉的发音卡不能吞掉仍可安全展示的澄清。"""
    raw = {
        "act": "clarify", "content": "你说的是上面的哪一个单词？请点一下或把它发给我。",
        "pronounce": {"lesson": {"source_text": "", "locale": "en-US", "notes": []}},
        "lesson": {"source_text": "", "locale": "en-US", "notes": []},
    }
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.lesson is None
    assert _verdict(raw).ok


def test_a_subobject_of_another_act_is_dropped_not_rejected():
    """lesson / candidates 只属于各自的 act；放错位置时丢弃，回答照常展示。"""
    raw = tutor_raw(
        "answer", "这个词是 in advance。", relation="none",
        pronounce={"lesson": LESSON}, clarify={"candidates": ["a", "b"]}, lesson=LESSON,
    )
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.lesson is None
    assert candidate.candidates == []
    assert _verdict(raw).ok


def test_clarify_keeps_candidates_even_when_they_are_top_level():
    raw = {"act": "clarify", "content": "是哪一句？", "candidates": ["第一句", "第二句"]}
    assert TutorTurnCandidate.model_validate(raw).candidates == ["第一句", "第二句"]


@pytest.mark.parametrize("act", ["answer", "guide"])
def test_answer_acts_must_say_which_kind_of_turn_this_is(act):
    """turn 是判别联合，缺失或不合法时不猜，走一次结构重试。"""
    for turn in (None, {}, {"type": "work"}, {"type": "work", "relation": "none"},
                 {"type": "work", "relation": "bogus"}, {"type": "other"}):
        raw = {"act": act, "content": "这个词是 in advance。"}
        if turn is not None:
            raw["turn"] = turn
        with pytest.raises(ValidationError):
            TutorTurnCandidate.model_validate(raw)


def test_guide_is_business_type_work_and_needs_the_work_branch():
    with pytest.raises(ValidationError):
        TutorTurnCandidate.model_validate(tutor_raw("guide", "先读题。", relation="none"))


def test_answer_takes_the_non_work_branch_and_a_work_claim_on_it_is_protected_but_never_advances():
    ok = TutorTurnCandidate.model_validate(tutor_raw("answer", "海滩。", relation="none"))
    assert ok.relation == "none" and ok.topic == "atomic_lookup" and ok.work is None
    claimed = _verdict(tutor_raw("answer", "地球绕太阳转。", relation="new"))
    assert claimed.ok and claimed.answer_protected and claimed.needs_leak_check
    assert not claimed.effective_work_product


def test_the_turn_branch_can_be_inferred_from_its_own_fields_only():
    work = TutorTurnCandidate.model_validate(
        {"act": "guide", "content": "先读题。", "turn": {"relation": "same", "student_move": "attempt"}})
    assert work.relation == "same"
    non_work = TutorTurnCandidate.model_validate(
        {"act": "answer", "content": "因为散射。", "turn": {"topic": "spontaneous_curiosity"}})
    assert non_work.topic == "spontaneous_curiosity"


def test_only_the_work_branch_carries_work_fields():
    candidate = TutorTurnCandidate.model_validate(
        {"act": "answer", "content": "海滩。",
         "turn": {"type": "non_work", "relation": "same", "progress": "submitted", "evidence": "x=3"}})
    assert candidate.relation == "none" and candidate.progress is None and candidate.subgoal_evidence is None


def test_a_turn_on_an_act_that_cannot_use_it_is_dropped_and_chat_is_its_own_topic():
    candidate = TutorTurnCandidate.model_validate(
        {"act": "chat", "content": "好的。", "turn": {"type": "work", "relation": "new"}})
    assert candidate.turn is None and candidate.relation == "none" and candidate.topic == "chat"


@pytest.mark.parametrize("act", ["chat", "redirect", "clarify", "safety"])
def test_other_acts_default_to_no_work(act):
    candidate = TutorTurnCandidate.model_validate({"act": act, "content": "好的。"})
    assert candidate.relation == "none"


def test_unknown_metadata_values_are_not_reported_instead_of_failing():
    raw = tutor_raw("guide", "再想一步。", progress="solved", student_move="whatever")
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.progress is None
    assert candidate.student_move == "other"
    assert _verdict(raw).ok


def test_answer_on_protected_work_is_judged_on_its_content_not_rejected_for_its_labels():
    """红线只是不把作业答案交给孩子：act=answer 加 relation=same|new 走泄露检查，不因标签矛盾整轮回退。"""
    protected = TutorPermit(True, AttemptSummary())
    answer = tutor_raw("answer", "自转是地球绕地轴转。", relation="same")
    verdict = _verdict(answer, permit=protected)
    assert verdict.ok and verdict.answer_protected and verdict.needs_leak_check
    assert not verdict.effective_work_product  # an answer never opens or advances a problem record
    guide = tutor_raw("guide", "先移项。", relation="same")
    verdict = _verdict(guide, permit=protected)
    assert verdict.ok and verdict.answer_protected and verdict.needs_leak_check


def test_relation_none_cannot_switch_off_protection_on_a_protected_problem():
    """红线归代码策略：有受保护的题时，answer/guide 一律检查内容，relation=none 只管不推进题目。"""
    protected = TutorPermit(True, AttemptSummary())
    verdict = _verdict(tutor_raw("answer", "海滩。", relation="none"), permit=protected)
    assert verdict.ok and verdict.answer_protected and verdict.needs_leak_check
    assert not verdict.effective_work_product


def test_relation_none_without_a_protected_problem_is_not_checked():
    verdict = _verdict(tutor_raw("answer", "海滩。", relation="none"))
    assert verdict.ok and not verdict.answer_protected and not verdict.needs_leak_check


def test_relation_new_on_a_protected_problem_stays_protected():
    protected = TutorPermit(True, AttemptSummary())
    assert _verdict(tutor_raw("guide", "先读题。", relation="new"), permit=protected).answer_protected


def test_a_new_work_product_question_starts_protected_without_an_open_problem():
    verdict = _verdict(tutor_raw("guide", "先读题。", relation="new"))
    assert verdict.answer_protected and verdict.effective_work_product
    answer = _verdict(tutor_raw("answer", "地球绕太阳转。", relation="new"))
    assert answer.ok and answer.answer_protected and answer.needs_leak_check and not answer.effective_work_product


def test_clarify_candidates_copied_as_ref_text_objects_show_their_text():
    """2026-10-11 线上：模型照抄 history_candidates 的 {ref,text}，孩子曾看到 dict 的 repr。"""
    raw = {"act": "clarify", "content": "你想听哪几个？", "clarify": {"candidates": [
        {"ref": "u5", "text": "amazed, shocked, astonished"}, "surprised", {"ref": "u1"}, 7, "  ",
    ]}}
    assert TutorTurnCandidate.model_validate(raw).candidates == ["amazed, shocked, astonished", "surprised"]


def test_work_depth_defaults_to_reasoning_and_unknown_values_are_the_most_protective():
    for depth in (None, "", "deep", 3):
        raw = tutor_raw("guide", "先读题。")
        if depth is not None:
            raw["turn"]["depth"] = depth
        assert TutorTurnCandidate.model_validate(raw).depth == "reasoning"
    for depth in ("atomic", "recall", "reasoning"):
        assert TutorTurnCandidate.model_validate(tutor_raw("guide", "先读题。", depth=depth)).depth == depth
    assert TutorTurnCandidate.model_validate(tutor_raw("answer", "海滩。", relation="none")).depth is None


def test_a_direct_answer_to_a_single_fact_inside_homework_is_still_checked_and_never_advances():
    protected = TutorPermit(True, AttemptSummary())
    for depth in ("atomic", "recall"):
        verdict = _verdict(tutor_raw("answer", "斜边是最长的边。", relation="same", depth=depth), permit=protected)
        assert verdict.ok and verdict.answer_protected and verdict.needs_leak_check
        assert not verdict.effective_work_product


def test_fields_removed_in_v4_are_ignored_and_never_reach_the_ward():
    """content 是孩子看到的全部文字：模型仍返回 follow_up_question/history_ref 时丢弃，不拒绝。"""
    raw = tutor_raw("answer", "海滩。", relation="none", follow_up_question="还想知道什么？", history_ref="u0")
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.shown_text == "海滩。"
    assert not hasattr(candidate, "follow_up_question") and not hasattr(candidate, "history_ref")
    assert _verdict(raw).ok


def test_progress_and_evidence_belong_to_an_attempt_only():
    hint = TutorTurnCandidate.model_validate(
        tutor_raw("guide", "先读题。", student_move="request_hint", progress="submitted", evidence="x=3"))
    assert hint.progress is None and hint.subgoal_evidence is None
    attempt = TutorTurnCandidate.model_validate(
        tutor_raw("guide", "你算出来了，再检查一下？", student_move="attempt", progress="submitted", evidence="x=3"))
    assert attempt.progress == "submitted" and attempt.subgoal_evidence == "x=3"


def test_chat_is_not_a_topic_the_model_can_write():
    candidate = TutorTurnCandidate.model_validate(
        {"act": "answer", "content": "因为散射。", "turn": {"type": "non_work", "topic": "chat"}})
    assert candidate.topic == "atomic_lookup"


def test_clarify_on_a_protected_problem_is_held_to_the_content_check():
    """候选也给孩子看：题目受保护时，澄清不能成为不经泄露检查的出口。"""
    protected = TutorPermit(True, AttemptSummary())
    plain = {"act": "clarify", "content": "你问的是哪一题？", "clarify": {"candidates": ["第一题", "第二题"]}}
    verdict = _verdict(plain, permit=protected)
    assert verdict.ok and verdict.answer_protected and verdict.needs_leak_check
    assert not verdict.effective_work_product


def test_clarify_without_a_protected_problem_is_not_checked():
    verdict = _verdict({"act": "clarify", "content": "是哪一句？", "clarify": {"candidates": ["最终答案是 3"]}})
    assert verdict.ok and not verdict.needs_leak_check
