import pytest
from pydantic import ValidationError

from app.application.workflows.tutor_turn import TutorTurnCandidate, check_authority
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit

PERMIT = TutorPermit(False, AttemptSummary())


def _verdict(raw: dict):
    return check_authority(
        TutorTurnCandidate.model_validate(raw), PERMIT,
        has_open_problem=False, authorized_history_refs=frozenset({"u0"}), has_work_input=True,
    )


def test_blank_next_subgoal_keeps_a_knowledge_reply():
    """空字符串不是小目标。知识问答不能因此整轮回退。"""
    raw = {
        "act": "answer", "question_kind": "knowledge_lookup",
        "content": "提前用英语是 *in advance*。",
        "follow_up_question": "现在我们继续完成正在进行的任务，需要我帮你回顾一下吗？",
        "candidates": [], "student_turn_kind": "ask_answer", "progress": "none",
        "same_problem": False, "is_assignment_content": False, "reveals_solution": False,
        "subgoal_evidence": "", "next_subgoal": "   ", "history_ref": "u0", "lesson": None,
        "permit": {"answer_protected": False},
    }
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.next_subgoal is None
    assert candidate.subgoal_evidence is None
    verdict = _verdict(raw)
    assert verdict.ok
    assert verdict.effective_work_product is False
    assert verdict.history_ref == "u0"


def test_pronounce_without_question_kind_keeps_the_lesson():
    """发音卡不使用 question_kind。漏填不能把已经完整的读法整轮丢掉。"""
    raw = {
        "act": "pronounce",
        "lesson": {
            "source_text": "in advance",
            "locale": "en-US",
            "introduction": "我们来一起读这个短语，它表示‘提前’的意思。",
            "reading_guide": "注意重音在第一个音节：in *a*dvance。",
            "notes": [
                {"kind": "stress", "segment": "in", "explanation": "in 是轻读音节，不强调。"},
                {"kind": "stress", "segment": "advance", "explanation": "advance 的重音在第一个音节。"},
            ],
        },
        "content": "‘in advance’ 读作 /ɪn ədˈvæns/，意思是‘提前’。",
    }
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.question_kind == "chat"
    verdict = _verdict(raw)
    assert verdict.ok
    assert candidate.lesson is not None
    assert candidate.lesson.source_text == "in advance"


def test_flat_pronounce_fields_become_a_lesson():
    """模型常把发音字段摊在最外层。收成 lesson 后才能投影发音卡。"""
    raw = {
        "act": "pronounce",
        "question_kind": "knowledge_lookup",
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


def test_answer_without_question_kind_still_fails():
    raw = {"act": "answer", "content": "这个词是 in advance。"}
    with pytest.raises(ValidationError):
        TutorTurnCandidate.model_validate(raw)


def test_real_next_subgoal_on_knowledge_lookup_is_rejected():
    raw = {
        "act": "answer", "question_kind": "knowledge_lookup", "content": "这个词是 in advance。",
        "student_turn_kind": "other", "same_problem": False, "is_assignment_content": False,
        "reveals_solution": False, "next_subgoal": "写出第一个等式",
    }
    verdict = _verdict(raw)
    assert not verdict.ok
    assert verdict.reason == "subgoal_without_work_product"
