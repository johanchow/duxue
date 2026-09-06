from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentType = Literal["planning", "tutoring", "reflection"]
RouteTarget = Literal["planning", "tutoring", "reflection", "clarify", "safety"]
RunStatus = Literal["active", "waiting_for_ward", "paused", "closed", "escalated"]


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


class CoordinatorResult(BaseModel):
    thread_id: str
    thread_version: int
    decision: RouteDecision
    run_id: str | None = None
    run_status: RunStatus | None = None
    context: dict | None = None
    interaction: dict | None = None
