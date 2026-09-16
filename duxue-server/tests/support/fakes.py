from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.application.ports.companion import (
    RunInvocation,
    WorkflowOutcome,
)
from app.infrastructure.ai.model_gateway import AgentTextCandidate, ModelGatewayError


class FakeModelGateway:
    def __init__(self, candidate: AgentTextCandidate | None = None, raise_error: bool = False):
        self.candidate = candidate or AgentTextCandidate(content="启发式测试建议")
        self.raise_error = raise_error
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, agent_type: str, envelope: dict, instruction: str) -> AgentTextCandidate:
        self.calls.append({"agent_type": agent_type, "envelope": envelope, "instruction": instruction})
        if self.raise_error:
            raise ModelGatewayError("fake model error")
        return self.candidate


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
