"""Transactional recording of immutable learning facts and downstream work."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import (
    DerivedSignal,
    EpisodicMemory,
    EpisodicMemoryEvent,
    GuardianWard,
    LearningEvent,
    LongTermProfile,
    OutboxEvent,
    now,
)


def record_learning_event(
    db: Session,
    *,
    ward_id: str,
    event_type: str,
    source_type: str,
    source_id: str,
    source_version: int = 1,
    occurred_at: datetime | None = None,
    source: str = "system",
    confidence: float | None = None,
    scope: dict | None = None,
    payload: dict | None = None,
    evidence_refs: list | None = None,
    visibility: str = "system",
) -> LearningEvent:
    """Append a fact once and enqueue its derivation in the same transaction.

    The source identity/version unique key makes retries harmless.  Consumers may
    build episodic memory, signals and profiles independently from the outbox.
    """
    existing = (
        db.query(LearningEvent)
        .filter_by(
            source_type=source_type,
            source_id=source_id,
            event_type=event_type,
            source_version=source_version,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing
    event = LearningEvent(
        ward_id=ward_id,
        event_type=event_type,
        occurred_at=occurred_at or now(),
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        source=source,
        confidence=confidence,
        scope=scope or {},
        payload=payload or {},
        evidence_refs=evidence_refs or [],
        visibility=visibility,
    )
    db.add(event)
    db.flush()
    db.add(
        OutboxEvent(
            aggregate_type="learning_event",
            aggregate_id=event.id,
            event_type="learning_event.recorded",
            payload={"learning_event_id": event.id},
        )
    )
    return event


MemoryType = Literal["working", "episodic", "signal", "profile"]
ActorRole = Literal["ward", "guardian", "system"]
UseCase = Literal["planning", "tutoring", "reflection"]


class MemoryContextRequest(BaseModel):
    ward_id: str
    actor_id: str
    actor_role: ActorRole
    use_case: UseCase
    task_id: str | None = None
    study_session_id: str | None = None
    tutoring_session_id: str | None = None
    skill_keys: list[str] = Field(default_factory=list)
    memory_types: set[MemoryType] = Field(default_factory=set)
    visibility_scope: set[Literal["ward", "guardian", "system"]] = Field(
        default_factory=set
    )
    item_budget: int = Field(ge=1, le=100)
    token_budget: int = Field(ge=64, le=20_000)


class MemoryBundle(BaseModel):
    working_state: dict | None = None
    episodic_memories: list[dict] = Field(default_factory=list)
    active_signals: list[dict] = Field(default_factory=list)
    profile_projection: dict | None = None
    evidence_refs: list[dict] = Field(default_factory=list)
    retrieval_version: str = "memory-facade.v1"
    truncated: bool = False


class MemoryAccessDenied(PermissionError):
    pass


class SqlAlchemyMemoryFacade:
    """The only Agent-facing aggregation reader for Ward memory.

    It intentionally projects summaries and evidence identifiers rather than
    conversation bodies, raw cues, or candidate conclusions.
    """

    def __init__(self, db: Session):
        self.db = db

    def _authorize(self, request: MemoryContextRequest) -> None:
        if request.actor_role == "system":
            return
        if (
            request.actor_role == "ward"
            and request.actor_id == request.ward_id
            and request.visibility_scope <= {"ward", "system"}
        ):
            return
        if request.actor_role == "guardian":
            related = (
                self.db.query(GuardianWard)
                .filter_by(
                    guardian_id=request.actor_id,
                    ward_id=request.ward_id,
                )
                .one_or_none()
            )
            if related is not None and request.visibility_scope <= {
                "guardian",
                "system",
            }:
                return
        raise MemoryAccessDenied(
            "actor is not allowed to access this Ward memory scope"
        )

    @staticmethod
    def _estimate_tokens(item: dict) -> int:
        return max(1, len(str(item)) // 4)

    def resolve_context(self, request: MemoryContextRequest) -> MemoryBundle:
        self._authorize(request)
        remaining_items = request.item_budget
        remaining_tokens = request.token_budget
        truncated = False
        episodic: list[dict] = []
        signals: list[dict] = []
        evidence_refs: list[dict] = []

        def append_if_budget(target: list[dict], item: dict) -> bool:
            nonlocal remaining_items, remaining_tokens, truncated
            cost = self._estimate_tokens(item)
            if remaining_items <= 0 or cost > remaining_tokens:
                truncated = True
                return False
            target.append(item)
            remaining_items -= 1
            remaining_tokens -= cost
            return True

        if "episodic" in request.memory_types:
            cutoff = now().date() - timedelta(days=5)
            rows = (
                self.db.query(EpisodicMemory)
                .filter(
                    EpisodicMemory.ward_id == request.ward_id,
                    EpisodicMemory.event_date >= cutoff,
                )
                .order_by(
                    EpisodicMemory.event_date.desc(), EpisodicMemory.created_at.desc()
                )
                .all()
            )
            for row in rows:
                skill_keys = row.raw_cues.get("skill_keys", [])
                if request.skill_keys and not set(request.skill_keys).intersection(
                    skill_keys
                ):
                    continue
                item = {
                    "id": row.id,
                    "event_type": row.event_type,
                    "event_date": row.event_date.isoformat(),
                    "summary": row.summary,
                    "decay_weight": row.decay_weight,
                }
                if append_if_budget(episodic, item):
                    evidence_rows = (
                        self.db.query(EpisodicMemoryEvent, LearningEvent)
                        .join(
                            LearningEvent,
                            LearningEvent.id == EpisodicMemoryEvent.learning_event_id,
                        )
                        .filter(EpisodicMemoryEvent.episodic_memory_id == row.id)
                        .all()
                    )
                    evidence_refs.extend(
                        {
                            "memory_id": row.id,
                            "event_id": event.id,
                            "event_type": event.event_type,
                        }
                        for _, event in evidence_rows
                    )

        if "signal" in request.memory_types:
            rows = (
                self.db.query(DerivedSignal)
                .filter(
                    DerivedSignal.ward_id == request.ward_id,
                    DerivedSignal.status == "active",
                )
                .order_by(DerivedSignal.last_evaluated_at.desc())
                .all()
            )
            for row in rows:
                if row.expires_at is not None and row.expires_at < now():
                    continue
                signal_skill_key = row.value.get("skill_key")
                if (
                    request.skill_keys
                    and signal_skill_key is not None
                    and signal_skill_key not in request.skill_keys
                ):
                    continue
                append_if_budget(
                    signals,
                    {
                        "id": row.id,
                        "signal_type": row.signal_type,
                        "scope": row.scope,
                        "value": row.value,
                        "statement": row.statement,
                        "confidence": row.confidence,
                        "evidence_status": "active",
                    },
                )

        profile_projection = None
        if "profile" in request.memory_types:
            profile = self.db.get(LongTermProfile, request.ward_id)
            if profile is not None:
                projection = {
                    "focus_endurance_baseline_min": profile.focus_endurance_baseline_min,
                    "subject_difficulty_map": profile.subject_difficulty_map,
                    "learning_strategy_profile": profile.learning_strategy_profile,
                    "planning_preferences": profile.planning_preferences,
                    "profile_version": profile.profile_version,
                }
                if (
                    remaining_items > 0
                    and self._estimate_tokens(projection) <= remaining_tokens
                ):
                    profile_projection = projection
                    remaining_items -= 1
                    remaining_tokens -= self._estimate_tokens(projection)
                else:
                    truncated = True

        return MemoryBundle(
            episodic_memories=episodic,
            active_signals=signals,
            profile_projection=profile_projection,
            evidence_refs=evidence_refs,
            truncated=truncated,
        )
