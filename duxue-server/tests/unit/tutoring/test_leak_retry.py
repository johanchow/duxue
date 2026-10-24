"""文字给出了答案时重试一次改成提示；重试结果重新完整检查，fallback 只按最终结果记一次。"""

import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.application.workflows import tutor_loop
from app.application.workflows.tutor_loop import LEAK_REPAIR, run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutoring_workflow import TutoringWorkflow
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


def _run(model, judge, monkeypatch=None, backup_model=None):
    fallbacks: list[str] = []
    if monkeypatch is not None:
        monkeypatch.setattr(tutor_loop, "record_llm_fallback", lambda **kw: fallbacks.append(kw["reason"]))
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = run_tutor_turn(
        model, {}, "{}", [], [], tools, permit=PROTECTED, leak_judge=judge,
        task_title="数学作业", problem_summary="第1题：解方程 x+3=7", backup_model=backup_model,
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


def test_a_retry_that_still_leaks_falls_back_once(monkeypatch):
    model = StaticTutorModel(LEAKY)
    result, fallbacks = _run(model, StaticLeakJudge(True), monkeypatch)
    assert result.leak_retried and result.vetting.failure == "leak_detected"
    assert len(model.calls) == 2 and fallbacks == ["leak_detected"]


def test_same_leak_reason_uses_backup_model_and_rechecks_it(monkeypatch):
    model = StaticTutorModel(LEAKY)
    backup = StaticTutorModel(HINT)
    result, fallbacks = _run(model, LeaksWhen("等于 4"), monkeypatch, backup_model=backup)
    assert len(model.calls) == 2 and len(backup.calls) == 1
    assert "被拒草稿" in backup.calls[0]["repair_error"]
    assert result.vetting.failure is None and result.call.candidate.content == HINT["content"]
    assert fallbacks == []


def test_backup_model_cannot_bypass_the_leak_judge(monkeypatch):
    model = StaticTutorModel(LEAKY)
    backup = StaticTutorModel(LEAKY)
    result, fallbacks = _run(model, LeaksWhen("等于 4"), monkeypatch, backup_model=backup)
    assert len(backup.calls) == 1
    assert result.vetting.failure == "leak_detected" and fallbacks == ["leak_detected"]


def test_all_rejected_attempts_keep_candidate_review_input_and_reason_in_one_trace(monkeypatch):
    from app.infrastructure.observability import telemetry

    class ExplainsLeak(StaticLeakJudge):
        def leaks(self, *, text, task_title, problem_summary):
            return {"leaks": True, "reason": "final_answer"}

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with telemetry.agent_turn_span():
        result, _ = _run(StaticTutorModel(LEAKY), ExplainsLeak(), backup_model=StaticTutorModel(LEAKY))

    assert result.vetting.failure == "leak_detected"
    spans = exporter.get_finished_spans()
    attempts = [s for s in spans if s.attributes.get("agent.step") == "tutoring.attempt"]
    assert [s.attributes["tutor.attempt.kind"] for s in attempts] == ["primary", "repair", "backup"]
    reviews = [s for s in spans if s.attributes.get("agent.step") == "tutoring.exit_gate"]
    assert len(reviews) == 3
    assert {s.parent.span_id for s in reviews} == {s.context.span_id for s in attempts}
    leak_checks = [s for s in spans if s.attributes.get("agent.step") == "tutoring.text_leak"]
    assert len(leak_checks) == 3
    assert {s.parent.span_id for s in leak_checks} == {s.context.span_id for s in reviews}
    for check in leak_checks:
        check_input = json.loads(check.attributes["langfuse.observation.input"])
        check_output = json.loads(check.attributes["langfuse.observation.output"])
        assert check_input["reply"] == LEAKY["content"]
        assert check_input["problem"] == "第1题：解方程 x+3=7"
        assert check_output == {"leaks": True, "reason": "final_answer"}
    for review in reviews:
        input_payload = json.loads(review.attributes["langfuse.observation.input"])
        output_payload = json.loads(review.attributes["langfuse.observation.output"])
        assert input_payload["candidate"]["content"] == LEAKY["content"]
        assert input_payload["permit"]["answer_protected"] is True
        assert input_payload["problem_summary"] == "第1题：解方程 x+3=7"
        assert output_payload["failure"] == "leak_detected"
        assert output_payload["leak_reason"] == "final_answer"
        assert review.attributes["tutor.leak.reason"] == "final_answer"


def test_rejected_schema_retries_keep_the_raw_candidate_and_error(monkeypatch):
    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    invalid = {"act": "guide", "content": "先想一想。"}  # missing work turn
    with telemetry.agent_turn_span():
        result, _ = _run(StaticTutorModel(invalid), StaticLeakJudge(False))

    assert result.call.candidate is None
    checks = [s for s in exporter.get_finished_spans()
              if s.attributes.get("agent.step") == "tutoring.candidate_schema"]
    assert len(checks) == 2
    for check in checks:
        assert json.loads(check.attributes["langfuse.observation.input"]) == invalid
        outcome = json.loads(check.attributes["langfuse.observation.output"])
        assert outcome["result"] == "rejected" and outcome["reason"]


def test_workflow_passes_backup_model_to_the_shared_exit_checks():
    backup = StaticTutorModel(HINT)
    workflow = TutoringWorkflow(
        None, turn_model=StaticTutorModel(LEAKY), backup_model=backup,
        leak_judge=LeaksWhen("等于 4"),
    )
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = workflow._run_model(
        {}, "{}", [], [], tools, permit=PROTECTED,
        task_title="数学作业", problem_summary="第1题：解方程 x+3=7",
    )
    assert len(backup.calls) == 1
    assert result.vetting.failure is None


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
