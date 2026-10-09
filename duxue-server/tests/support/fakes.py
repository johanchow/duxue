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


def tutor_raw(**fields) -> dict:
    """A valid tutor-turn.v1 candidate; override only what a test cares about."""
    base = {
        "act": "hint", "question_kind": "work_product_help", "content": "先说说已知条件是什么？",
        "follow_up_question": None, "candidates": [], "student_turn_kind": "ask_hint",
        "progress": None, "same_problem": True, "is_assignment_content": True,
        "reveals_solution": False, "history_ref": None, "lesson": None,
    }
    return {**base, **fields}


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
