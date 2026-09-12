"""Published-language contracts emitted by non-Memory bounded contexts.

The helper intentionally owns no Memory persistence.  A producer records its
own state and this Outbox row in one transaction; the Memory consumer later
interprets the stable fact through ``IngestLearningFact``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import OutboxEvent, now


def publish_learning_fact(
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
) -> OutboxEvent:
    """Publish a self-contained ``LearningFactRecorded.v1`` integration event.

    This is deliberately an Outbox-only operation: upstream contexts must not
    create ``LearningEvent`` rows, which are owned by Memory's evidence ledger.
    Consumer idempotency is keyed by the source identity/version in the payload.
    """
    occurred = occurred_at or now()
    event = OutboxEvent(
        aggregate_type=source_type,
        aggregate_id=source_id,
        event_type="LearningFactRecorded.v1",
        payload={
            "schema_version": "LearningFactRecorded.v1",
            "ward_id": ward_id,
            "event_type": event_type,
            "source_type": source_type,
            "source_id": source_id,
            "source_version": source_version,
            "occurred_at": occurred.isoformat(),
            "source": source,
            "confidence": confidence,
            "scope": scope or {},
            "payload": payload or {},
            "evidence_refs": evidence_refs or [],
            "visibility": visibility,
        },
    )
    db.add(event)
    return event
