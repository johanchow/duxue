from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

AgentType = Literal["planning", "tutoring", "reflection"]
RouteTarget = Literal["planning", "tutoring", "reflection", "clarify", "safety"]
RunStatus = Literal[
    "active", "waiting_for_ward", "paused", "closed", "escalated",
    "failed", "timed_out", "cancelled",
]


class RouteDecision(BaseModel):
    target: RouteTarget
    mode: Literal["start", "continue", "handoff", "clarify"]
    confidence: float = Field(ge=0, le=1)
    active_session_id: str | None = None
    route_reason: str
    context_refs: list[str] = Field(default_factory=list)


class ContextEnvelope(BaseModel):
    """Redacted, bounded input assembled before any future model call."""

    version: str = "companion-context.v1"
    run: dict
    actor: dict
    objective: dict
    session: dict
    evidence_refs: list[dict] = Field(default_factory=list)
    signals: list[dict] = Field(default_factory=list)
    memory: list[dict] = Field(default_factory=list)
    profile: dict | None = None
    policy: dict = Field(default_factory=dict)
    tools: list[dict] = Field(default_factory=list)
    truncated: bool = False

    def trace_snapshot(self) -> dict:
        """Persist metadata only; raw Ward content and model reasoning stay out."""
        return {
            "version": self.version,
            "run": self.run,
            "actor": {"role": self.actor["role"], "ward_id": self.actor["ward_id"]},
            "objective": self.objective,
            "evidence_ref_count": len(self.evidence_refs),
            "signal_count": len(self.signals),
            "memory_count": len(self.memory),
            "has_profile": self.profile is not None,
            "truncated": self.truncated,
        }


class ContextSpec(BaseModel):
    """The minimum, versioned context a workflow is permitted to request."""

    memory_types: set[Literal["episodic", "signal", "profile"]] = Field(
        default_factory=lambda: {"episodic", "signal", "profile"}
    )
    item_budget: int = Field(default=12, ge=1, le=100)
    token_budget: int = Field(default=900, ge=64, le=20_000)
    tool_allow_list: set[str] = Field(default_factory=set)
    max_model_calls: int = Field(default=0, ge=0, le=20)
    max_tool_calls: int = Field(default=0, ge=0, le=20)
    checkpoint_version: str = "v1"
    policy_version: str = "v1"


class RunInvocation(BaseModel):
    """An authorized, single-workflow instruction emitted by the Coordinator."""

    run_id: str
    thread_id: str
    ward_id: str
    agent_type: AgentType
    turn: dict
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    attempt: int = Field(default=1, ge=1)
    context_refs: list[str] = Field(default_factory=list)
    resume_from_checkpoint: bool = False


class WorkflowOutcome(BaseModel):
    """Validated workflow result; it contains no ORM objects or raw prompts."""

    run_status: RunStatus
    outcome_type: Literal["response", "waiting", "completed", "failure", "cancelled", "escalation"] | None = None
    response: dict[str, Any] | None = None
    next_interaction: dict | None = None
    context_refs: list[str] = Field(default_factory=list)
    checkpoint_ref: str | None = None
    context_snapshot: dict | None = None
    failure: dict[str, Any] | None = None
    resume_action: Literal["retry", "resume_from_checkpoint", "restart", "none"] = "none"
    handoff_suggestion: AgentType | None = None
    trace_id: str | None = None


class WorkflowDispatcher(Protocol):
    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome: ...


class CoordinatorResult(BaseModel):
    thread_id: str
    thread_version: int
    decision: RouteDecision
    run_id: str | None = None
    run_status: RunStatus | None = None
    context: dict | None = None
    interaction: dict | None = None
    command_id: str | None = None
