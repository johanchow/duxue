from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.application.ports.companion import (
    IntentProposal,
    RunInvocation,
    WorkflowOutcome,
)
from app.infrastructure.ai.model_gateway import AgentTextCandidate, ModelGatewayError


class FakeModelGateway:
    def __init__(self, candidate: AgentTextCandidate | None = None, raise_error: bool = False):
        self.candidate = candidate or AgentTextCandidate(content="启发式测试建议")
        self.raise_error = raise_error
        self.calls: list[dict[str, Any]] = []

    def generate(
        self, *, agent_type: str, envelope: dict, instruction: str,
        recent_utterances: list[dict] | None = None, current_images: list | None = None,
    ) -> AgentTextCandidate:
        self.calls.append({
            "agent_type": agent_type, "envelope": envelope, "instruction": instruction,
            "recent_utterances": list(recent_utterances or []), "current_images": list(current_images or []),
        })
        if self.raise_error:
            raise ModelGatewayError("fake model error")
        return self.candidate


def tutor_raw(act: str = "guide", content: str = "先说说已知条件是什么？", *, relation: str | None = "same",
              student_move: str = "request_hint", progress: str | None = None, evidence: str | None = None,
              next_subgoal: str | None = None, lesson: dict | None = None, candidates: list | None = None,
              **extra) -> dict:
    """A valid tutor-turn.v2 candidate; override only what a test cares about.

    ``relation=None`` omits ``work`` entirely.  ``extra`` is merged at the top level.
    """
    raw: dict = {"act": act, "content": content}
    if relation is not None:
        work = {"relation": relation, "student_move": student_move}
        for key, value in (("progress", progress), ("evidence", evidence), ("next_subgoal", next_subgoal)):
            if value is not None:
                work[key] = value
        raw["work"] = work
    if lesson is not None:
        raw["pronounce"] = {"lesson": lesson}
    if candidates:
        raw["clarify"] = {"candidates": candidates}
    return {**raw, **extra}


class StaticTutorModel:
    """Returns queued raw candidates in order (the last one repeats)."""

    def __init__(self, *raws: dict):
        self.raws = list(raws) or [tutor_raw()]
        self.calls: list[dict] = []

    def complete(
        self, *, envelope: dict, instruction: str, recent_utterances: list[dict] | None = None,
        current_images: list | None = None, repair_error: str | None = None,
        observations: list[dict] | None = None,
    ) -> dict:
        self.calls.append({"observations": list(observations or []),
            "envelope": envelope, "instruction": instruction,
            "recent_utterances": list(recent_utterances or []),
            "current_images": list(current_images or []), "repair_error": repair_error,
        })
        index = min(len(self.calls) - 1, len(self.raws) - 1)
        return self.raws[index]


class StaticLeakJudge:
    def __init__(self, result: bool | None = False):
        self.result = result
        self.calls = 0

    def leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        self.calls += 1
        return self.result


class StaticVisualLeakJudge(StaticLeakJudge):
    """A text judge that can also judge a diagram.  ``visual_result`` may be an exception to raise."""

    def __init__(self, result: bool | None = False, visual_result: bool | None | Exception = False):
        super().__init__(result)
        self.visual_result = visual_result
        self.visual_texts: list[str] = []

    def visual_leaks(self, *, text: str, task_title: str | None, problem_summary: str | None) -> bool | None:
        self.visual_texts.append(text)
        if isinstance(self.visual_result, Exception):
            raise self.visual_result
        return self.visual_result


class StaticSafetyScreening:
    def __init__(self, *, input_blocked: bool = False, output_blocked: bool = False):
        self.input_blocked = input_blocked
        self.output_blocked = output_blocked
        self.input_calls = 0
        self.output_calls = 0

    def blocks_input(self, *, text: str) -> bool:
        self.input_calls += 1
        return self.input_blocked

    def blocks_output(self, *, text: str) -> bool:
        self.output_calls += 1
        return self.output_blocked


class StaticIntentClassifier:
    def __init__(self, intent: str = "planning"):
        self.intent = intent

    def propose(
        self, *, content: str, focus_agent_type: str | None, recent_utterances: list[dict] | None = None,
        current_images: list | None = None,
    ) -> IntentProposal:
        return IntentProposal(intent=self.intent)


class FakeWorkflowDispatcher:
    def __init__(self, default_outcome: WorkflowOutcome | None = None):
        self.default_outcome = default_outcome or WorkflowOutcome(
            run_status="waiting_for_ward",
            outcome_type="waiting",
            next_interaction={"status": "needs_input", "content": "请回答"},
        )
        self.invocations: list[RunInvocation] = []

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        self.invocations.append(invocation)
        return self.default_outcome


class FakeClock:
    def __init__(self, initial_time: datetime | None = None):
        self._current_time = initial_time or datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current_time

    def advance(self, **kwargs) -> datetime:
        from datetime import timedelta
        self._current_time += timedelta(**kwargs)
        return self._current_time
