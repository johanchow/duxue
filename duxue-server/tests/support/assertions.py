from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import AgentRun, AgentTrace, DerivedSignal, EpisodicMemory, LearningEvent, OutboxEvent


def assert_fact_recorded(
    db: Session,
    ward_id: str,
    event_type: str,
    *,
    expected_payload: dict[str, Any] | None = None,
) -> LearningEvent:
    events = (
        db.query(LearningEvent)
        .filter(LearningEvent.ward_id == ward_id, LearningEvent.event_type == event_type)
        .all()
    )
    assert events, f"Expected LearningEvent of type {event_type} for ward {ward_id}, but found none"
    event = events[-1]
    if expected_payload:
        for key, value in expected_payload.items():
            assert event.payload.get(key) == value, (
                f"Fact payload mismatch for {key}: expected {value}, got {event.payload.get(key)}"
            )
    return event


def assert_outbox_event_published(
    db: Session,
    event_type: str,
    *,
    status: str = "published",
) -> OutboxEvent:
    outbox = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.event_type == event_type, OutboxEvent.status == status)
        .first()
    )
    assert outbox is not None, f"Expected OutboxEvent {event_type} with status {status}"
    return outbox


def assert_fenced_outcome(
    db: Session,
    run_id: str,
    expected_status: str,
) -> AgentRun:
    run = db.get(AgentRun, run_id)
    assert run is not None, f"AgentRun {run_id} not found"
    assert run.status == expected_status, (
        f"Expected run {run_id} status to be {expected_status}, but was {run.status}"
    )
    return run


def assert_active_signal_present(
    db: Session,
    ward_id: str,
    signal_type: str,
    dimension_key: str,
) -> DerivedSignal:
    signal = (
        db.query(DerivedSignal)
        .filter_by(
            ward_id=ward_id,
            signal_type=signal_type,
            dimension_key=dimension_key,
            status="active",
        )
        .first()
    )
    assert signal is not None, (
        f"Expected active signal {signal_type}:{dimension_key} for ward {ward_id}"
    )
    return signal
