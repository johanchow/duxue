"""Reliable local worker entrypoints for the Memory & Understanding Context."""

from __future__ import annotations

from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from .memory import LearningFactRecorded, SqlAlchemyMemoryCommandService
from .models import DerivedSignal, OutboxEvent, Ward, now


def consume_pending_learning_facts(db: Session, *, limit: int = 100) -> int:
    """Consume committed Fact Outbox rows with retry/dead-letter semantics.

    The Evidence Ledger source four-tuple remains the final idempotency fence;
    this worker's status only prevents unnecessary repeat delivery.
    """
    rows = db.query(OutboxEvent).filter(
        OutboxEvent.event_type == "LearningFactRecorded.v1",
        OutboxEvent.status.in_(["pending", "retry"]),
        OutboxEvent.available_at <= now(),
    ).order_by(OutboxEvent.created_at).with_for_update(skip_locked=True).limit(limit).all()
    completed = 0
    service = SqlAlchemyMemoryCommandService(db)
    for row in rows:
        row.attempts += 1
        try:
            fact = LearningFactRecorded.model_validate(row.payload)
            service.ingest_learning_fact(fact)
            if fact.event_type == "tutoring.session_closed":
                tutoring_session_id = str(fact.payload.get("tutoring_session_id", ""))
                if tutoring_session_id:
                    service.settle_tutoring_episode(tutoring_session_id)
            service.evolve_signals()
            service.rebuild_long_term_profile(fact.ward_id)
            row.status, row.published_at, row.last_error = "published", now(), None
            completed += 1
        except ValidationError as error:
            row.status, row.last_error = "dead", str(error)[:500]
        except Exception as error:  # retryable infrastructure/database failure
            row.status, row.last_error = "retry", str(error)[:500]
            row.available_at = now() + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
    db.commit()
    return completed


def run_memory_maintenance(db: Session) -> dict[str, int]:
    """Scheduler entrypoint: decay/expire, archive hot episodes, rebuild views."""
    service = SqlAlchemyMemoryCommandService(db)
    changed = service.evolve_signals()
    archived = service.archive_episodic_memories()
    for ward_id in [row[0] for row in db.query(Ward.id).all()]:
        service.rebuild_long_term_profile(ward_id)
    db.commit()
    return {"signals_changed": len(changed), "episodes_archived": archived}
