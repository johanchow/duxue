"""Transactional recording of immutable learning facts and downstream work."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import (
    DerivedSignal,
    DerivedSignalEvent,
    EpisodicMemory,
    EpisodicMemoryEvent,
    GuardianWard,
    LearningEvent,
    LongTermProfile,
    now,
)


def _record_learning_evidence(
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
    """Memory's private, idempotent Evidence Ledger write operation."""
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
    return event


MemoryType = Literal["episodic", "signal", "profile"]
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
    episodic_memories: list[dict] = Field(default_factory=list)
    active_signals: list[dict] = Field(default_factory=list)
    profile_projection: dict | None = None
    evidence_refs: list[dict] = Field(default_factory=list)
    retrieval_version: str = "memory-facade.v1"
    freshness: Literal["current", "eventually_consistent", "empty"] = "current"
    truncated: bool = False


class MemoryAccessDenied(PermissionError):
    pass


class LearningFactRecorded(BaseModel):
    """Versioned integration envelope accepted by the Memory boundary."""

    schema_version: Literal["LearningFactRecorded.v1"] = "LearningFactRecorded.v1"
    ward_id: str
    event_type: str
    source_type: str
    source_id: str
    source_version: int = Field(default=1, ge=1)
    occurred_at: datetime
    source: Literal["ward", "guardian", "system", "cam"] = "system"
    confidence: float | None = Field(default=None, ge=0, le=1)
    scope: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    evidence_refs: list = Field(default_factory=list)
    visibility: Literal["ward", "guardian", "system"] = "system"


class SqlAlchemyMemoryCommandService:
    """Application boundary for idempotently ingesting stable learning facts."""

    def __init__(self, db: Session):
        self.db = db

    def ingest_learning_fact(self, fact: LearningFactRecorded) -> LearningEvent:
        return _record_learning_evidence(
            self.db,
            ward_id=fact.ward_id,
            event_type=fact.event_type,
            source_type=fact.source_type,
            source_id=fact.source_id,
            source_version=fact.source_version,
            occurred_at=fact.occurred_at,
            source=fact.source,
            confidence=fact.confidence,
            scope=fact.scope,
            payload=fact.payload,
            evidence_refs=fact.evidence_refs,
            visibility=fact.visibility,
        )

    def settle_tutoring_episode(self, tutoring_session_id: str, version: int = 1) -> EpisodicMemory | None:
        """Settle only closed-session facts; never copy tutoring messages."""
        events = self.db.query(LearningEvent).filter(
            LearningEvent.event_type.in_([
                "tutoring.ward_attempt_recorded",
                "tutoring.understanding_confirmed",
                "tutoring.hint_given",
                "tutoring.session_closed",
            ]),
            LearningEvent.payload["tutoring_session_id"].as_string() == tutoring_session_id,
        ).all()
        ward_ids = {event.ward_id for event in events}
        has_closed = any(event.event_type == "tutoring.session_closed" for event in events)
        has_interaction = any(
            event.event_type in {
                "tutoring.ward_attempt_recorded",
                "tutoring.understanding_confirmed",
                "tutoring.hint_given",
            }
            for event in events
        )
        if not events or len(ward_ids) != 1 or not has_closed or not has_interaction:
            return None
        ref = f"tutoring_session:{tutoring_session_id}"
        memory = self.db.query(EpisodicMemory).filter_by(memory_type="tutoring_episode", aggregate_ref=ref, aggregate_version=version).one_or_none()
        if memory is None:
            occurred = max(event.occurred_at for event in events)
            memory = EpisodicMemory(
                ward_id=events[0].ward_id, event_type="tutoring_episode", memory_type="tutoring_episode",
                aggregate_ref=ref, aggregate_version=version, event_date=occurred.date(),
                summary="本次答疑已结算；可在下次学习时从已知条件开始。",
                raw_cues={}, hot_until=occurred + timedelta(days=5), expires_at=occurred + timedelta(days=30),
            )
            self.db.add(memory); self.db.flush()
        linked = {row.learning_event_id for row in self.db.query(EpisodicMemoryEvent).filter_by(episodic_memory_id=memory.id)}
        for event in events:
            if event.id not in linked:
                self.db.add(EpisodicMemoryEvent(episodic_memory_id=memory.id, learning_event_id=event.id))
        return memory

    def propose_candidate_signal(
        self,
        *,
        ward_id: str,
        signal_type: str,
        scope: str,
        dimension_key: str,
        value: dict,
        statement: str,
        confidence: float,
        evidence_event_ids: list[str],
        policy_version: str = "v1",
    ) -> DerivedSignal:
        """Create a reviewable candidate backed by ledger evidence only."""
        allowed = {
            "focus_endurance_baseline", "estimation_bias", "knowledge_gap",
            "effective_strategy", "stable_interest", "planning_preference",
            "reflection_accuracy_trend",
        }
        if signal_type not in allowed or scope not in {"recent", "long_term"}:
            raise ValueError("unsupported signal type or scope")
        if not dimension_key or not {"sample_size", "window", "calculation_method"} <= value.keys():
            raise ValueError("signal value must include sample_size, window and calculation_method")
        evidence = self.db.query(LearningEvent).filter(
            LearningEvent.id.in_(evidence_event_ids), LearningEvent.ward_id == ward_id
        ).all()
        if not evidence or len({event.id for event in evidence}) != len(set(evidence_event_ids)):
            raise ValueError("candidate signal requires authorized evidence")
        signal = self.db.query(DerivedSignal).filter_by(
            ward_id=ward_id, signal_type=signal_type, scope=scope, dimension_key=dimension_key
        ).one_or_none()
        if signal is None:
            signal = DerivedSignal(
                ward_id=ward_id, signal_type=signal_type, scope=scope,
                dimension_key=dimension_key, value=value, statement=statement,
                confidence=confidence, observed_from=min(event.occurred_at for event in evidence),
                status="candidate", policy_version=policy_version,
            )
            self.db.add(signal)
            self.db.flush()
        for event in evidence:
            if not self.db.query(DerivedSignalEvent).filter_by(
                derived_signal_id=signal.id, learning_event_id=event.id, role="support"
            ).one_or_none():
                self.db.add(DerivedSignalEvent(
                    derived_signal_id=signal.id, learning_event_id=event.id, role="support"
                ))
        # A challenged conclusion is never silently restored.  New evidence
        # only makes it eligible for an explicit policy re-evaluation.
        if signal.status == "challenged":
            signal.last_evaluated_at = now()
        return signal

    def challenge_signal(self, signal_id: str, ward_id: str, statement: str) -> DerivedSignal:
        signal = self.db.get(DerivedSignal, signal_id)
        if signal is None or signal.ward_id != ward_id:
            raise MemoryAccessDenied("signal is not visible to this Ward")
        fact = _record_learning_evidence(self.db, ward_id=ward_id, event_type="signal.ward_challenged", source_type="derived_signal", source_id=signal.id, source_version=1, source="ward", payload={"statement": statement}, visibility="ward")
        exists = self.db.query(DerivedSignalEvent).filter_by(derived_signal_id=signal.id, learning_event_id=fact.id, role="counterevidence").one_or_none()
        if exists is None:
            self.db.add(DerivedSignalEvent(derived_signal_id=signal.id, learning_event_id=fact.id, role="counterevidence"))
        signal.status = "challenged"; signal.last_evaluated_at = now()
        return signal

    def evolve_signals(self, at: datetime | None = None) -> list[DerivedSignal]:
        """Apply the versioned v1 threshold; only this worker may activate signals."""
        at = at or now()
        changed: list[DerivedSignal] = []
        for signal in self.db.query(DerivedSignal).filter(
            DerivedSignal.status.in_(["candidate", "active", "challenged"])
        ):
            if signal.expires_at is not None and signal.expires_at <= at:
                signal.status = "expired"; signal.last_evaluated_at = at; changed.append(signal)
                continue
            support_events = self.db.query(LearningEvent).join(
                DerivedSignalEvent, DerivedSignalEvent.learning_event_id == LearningEvent.id,
            ).filter(DerivedSignalEvent.derived_signal_id == signal.id, DerivedSignalEvent.role == "support").all()
            # Long-term conclusions require independent settled episodes, not
            # multiple messages in one tutoring session.
            episode_refs = {
                row.aggregate_ref
                for row in self.db.query(EpisodicMemory).join(
                    EpisodicMemoryEvent, EpisodicMemoryEvent.episodic_memory_id == EpisodicMemory.id,
                ).filter(
                    EpisodicMemoryEvent.learning_event_id.in_([event.id for event in support_events]),
                    EpisodicMemory.memory_type == "tutoring_episode",
                ).all()
            }
            counterevidence = self.db.query(DerivedSignalEvent).filter_by(
                derived_signal_id=signal.id, role="counterevidence"
            ).count()
            if (
                signal.status in {"candidate", "challenged"}
                and signal.scope == "long_term"
                and signal.confidence >= 0.75
                and len(episode_refs) >= 2
                and len(support_events) > counterevidence
            ):
                signal.status = "active"; signal.last_evaluated_at = at; changed.append(signal)
        return changed

    def rebuild_long_term_profile(self, ward_id: str) -> LongTermProfile:
        signals = self.db.query(DerivedSignal).filter(
            DerivedSignal.ward_id == ward_id,
            DerivedSignal.scope == "long_term",
            DerivedSignal.status == "active",
            (DerivedSignal.expires_at.is_(None)) | (DerivedSignal.expires_at > now()),
        ).all()
        profile = self.db.get(LongTermProfile, ward_id) or LongTermProfile(ward_id=ward_id)
        if self.db.get(LongTermProfile, ward_id) is None: self.db.add(profile)
        by_type: dict[str, dict] = {}
        for signal in signals:
            by_type.setdefault(signal.signal_type, {})[signal.dimension_key] = signal.value
        profile.planning_preferences = by_type.get("planning_preference", {})
        profile.learning_strategy_profile = by_type.get("effective_strategy", {})
        profile.mature_interest_radar = by_type.get("stable_interest", {})
        profile.subject_difficulty_map = by_type.get("knowledge_gap", {})
        profile.self_regulation_metrics = {
            **by_type.get("estimation_bias", {}),
            **by_type.get("reflection_accuracy_trend", {}),
        }
        focus = by_type.get("focus_endurance_baseline", {})
        profile.focus_endurance_baseline_meta = focus
        values = [value.get("minutes") for value in focus.values() if isinstance(value, dict) and isinstance(value.get("minutes"), int)]
        profile.focus_endurance_baseline_min = max(values) if values else None
        profile.profile_version = (profile.profile_version or 0) + 1
        return profile

    def archive_episodic_memories(self, at: datetime | None = None) -> int:
        at = at or now()
        rows = self.db.query(EpisodicMemory).filter(
            EpisodicMemory.archived_at.is_(None),
            (EpisodicMemory.hot_until.is_not(None)) & (EpisodicMemory.hot_until <= at),
        ).all()
        for row in rows:
            row.archived_at = at
        return len(rows)


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
                    EpisodicMemory.archived_at.is_(None),
                    (EpisodicMemory.hot_until.is_(None)) | (EpisodicMemory.hot_until > now()),
                    (EpisodicMemory.expires_at.is_(None)) | (EpisodicMemory.expires_at > now()),
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

        freshness: Literal["current", "eventually_consistent", "empty"] = "current"
        if not episodic and not signals and profile_projection is None:
            freshness = "empty"
        elif truncated:
            freshness = "eventually_consistent"
        return MemoryBundle(
            episodic_memories=episodic,
            active_signals=signals,
            profile_projection=profile_projection,
            evidence_refs=evidence_refs,
            truncated=truncated,
            freshness=freshness,
        )
