"""文字给出了答案时重试一次改成提示；重试结果重新完整检查，fallback 只按最终结果记一次。"""

from app.application.workflows import tutor_loop
from app.application.workflows.tutor_loop import LEAK_REPAIR, run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

PROTECTED = TutorPermit(True, AttemptSummary())
LEAKY = tutor_raw("guide", "先移项，x 就等于 4。")
HINT = tutor_raw("guide", "先想想：把 3 移到右边会怎样？")


class LeaksWhen(StaticLeakJudge):
    """Judges a reply as leaking when it contains ``marker``."""

    def __init__(self, marker: str):
        super().__init__()
        self.marker = marker

    def leaks(self, *, text, task_title, problem_summary):
        super().leaks(text=text, task_title=task_title, problem_summary=problem_summary)
        return self.marker in text


def _run(model, judge, monkeypatch=None):
    fallbacks: list[str] = []
    if monkeypatch is not None:
        monkeypatch.setattr(tutor_loop, "record_llm_fallback", lambda **kw: fallbacks.append(kw["reason"]))
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = run_tutor_turn(
        model, {}, "{}", [], [], tools, permit=PROTECTED, leak_judge=judge,
        task_title="数学作业", problem_summary="第1题：解方程 x+3=7",
    )
    return result, fallbacks


def test_a_leaking_reply_is_retried_once_and_the_hint_is_shown(monkeypatch):
    model = StaticTutorModel(LEAKY, HINT)
    result, fallbacks = _run(model, LeaksWhen("等于 4"), monkeypatch)
    assert result.leak_retried and result.vetting.failure is None
    assert result.call.candidate.content == HINT["content"]
    assert model.calls[0]["repair_error"] is None
    assert model.calls[1]["repair_error"].startswith(LEAK_REPAIR)
    assert LEAKY["content"] in model.calls[1]["repair_error"]
    assert fallbacks == []  # the first, blocked version is not a fallback


def test_an_answer_marker_is_retried_too(monkeypatch):
    model = StaticTutorModel(tutor_raw("guide", "最终答案是 4"), HINT)
    result, fallbacks = _run(model, StaticLeakJudge(False), monkeypatch)
    assert result.leak_retried and result.vetting.failure is None and fallbacks == []


def test_a_retry_that_still_leaks_falls_back_once(monkeypatch):
    model = StaticTutorModel(LEAKY)
    result, fallbacks = _run(model, StaticLeakJudge(True), monkeypatch)
    assert result.leak_retried and result.vetting.failure == "leak_detected"
    assert len(model.calls) == 2 and fallbacks == ["leak_detected"]


def test_retry_includes_a_specific_review_reason_when_available():
    class ExplainsLeak(StaticLeakJudge):
        def leaks(self, *, text, task_title, problem_summary):
            super().leaks(text=text, task_title=task_title, problem_summary=problem_summary)
            return {"leaks": True, "reason": "premature_conclusion"}

    model = StaticTutorModel(LEAKY, HINT)
    _run(model, ExplainsLeak())
    assert "premature_conclusion" in model.calls[1]["repair_error"]


def test_a_broken_judge_is_not_retried(monkeypatch):
    model = StaticTutorModel(LEAKY, HINT)
    result, fallbacks = _run(model, StaticLeakJudge(None), monkeypatch)
    assert not result.leak_retried and result.vetting.failure == "leak_check_failed"
    assert len(model.calls) == 1 and fallbacks == ["leak_check_failed"]


def test_a_retry_without_a_valid_candidate_keeps_the_original_reason(monkeypatch):
    model = StaticTutorModel(LEAKY, {"act": "guide", "content": "先想想。"})  # guide without turn: invalid
    result, fallbacks = _run(model, LeaksWhen("等于 4"), monkeypatch)
    assert result.leak_retried and result.vetting.failure == "leak_detected"
    assert len(model.calls) == 2  # the retry is itself the one repair: no further structure retry
    assert fallbacks == ["leak_detected"]


def test_a_shown_reply_is_not_retried(monkeypatch):
    model = StaticTutorModel(HINT)
    result, fallbacks = _run(model, StaticLeakJudge(False), monkeypatch)
    assert not result.leak_retried and result.vetting.failure is None
    assert len(model.calls) == 1 and fallbacks == []


def test_verified_calculation_confirmation_can_pass_the_same_protected_exit():
    model = StaticTutorModel(tutor_raw("guide", "你算出的 x=4 是正确的。"))
    result, _ = _run(model, StaticLeakJudge(False))
    assert result.vetting.failure is None
    assert not result.leak_retried


def test_choice_confirmation_still_retries_when_semantic_judge_rejects_it():
    model = StaticTutorModel(tutor_raw("guide", "B 是对的。"), HINT)
    result, _ = _run(model, LeaksWhen("B 是对的"))
    assert result.leak_retried
    assert result.vetting.failure is None
    assert result.call.candidate.content == HINT["content"]
