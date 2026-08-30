"""Transactional recording of immutable learning facts and downstream work."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import LearningEvent, OutboxEvent, now


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
    existing = db.query(LearningEvent).filter_by(
        source_type=source_type, source_id=source_id,
        event_type=event_type, source_version=source_version,
    ).one_or_none()
    if existing is not None:
        return existing
    event = LearningEvent(
        ward_id=ward_id, event_type=event_type, occurred_at=occurred_at or now(),
        source_type=source_type, source_id=source_id, source_version=source_version,
        source=source, confidence=confidence, scope=scope or {}, payload=payload or {},
        evidence_refs=evidence_refs or [], visibility=visibility,
    )
    db.add(event)
    db.flush()
    db.add(OutboxEvent(
        aggregate_type="learning_event", aggregate_id=event.id,
        event_type="learning_event.recorded", payload={"learning_event_id": event.id},
    ))
    return event
