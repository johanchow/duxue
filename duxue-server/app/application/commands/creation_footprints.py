"""Idempotent consumers and projections for CreationFootprintRecorded.v1.

Strictly isolates Ward creative exploration into Interest Signals (Memory) and
evening creation footprints (Evaluation) without touching academic mastery.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.application.commands.memory import _record_learning_evidence
from app.infrastructure.persistence.models import (
    CreativeWork,
    DerivedSignal,
    OutboxEvent,
    now,
)


def ingest_creation_interest_signal(
    db: Session,
    *,
    ward_id: str,
    artifact_id: str,
    version: int,
    title: str,
    occurred_at: datetime | None = None,
) -> dict:
    """Memory consumer: record independent Interest Signal, never academic mastery."""
    event = _record_learning_evidence(
        db,
        ward_id=ward_id,
        event_type="creation_footprint.recorded",
        source_type="artifact_workspace",
        source_id=artifact_id,
        source_version=version,
        occurred_at=occurred_at or now(),
        source="ward",
        confidence=1.0,
        scope={"domain": "creative_exploration", "academic_mastery": False},
        payload={"artifact_id": artifact_id, "version": version, "title": title},
        visibility="guardian",
    )
    signal_key = f"interest:creative:{artifact_id}"
    ts = occurred_at or now()
    existing = (
        db.query(DerivedSignal)
        .filter_by(
            ward_id=ward_id,
            signal_type="interest_signal",
            scope="creative",
            dimension_key=signal_key,
        )
        .one_or_none()
    )
    if existing is None:
        existing = DerivedSignal(
            ward_id=ward_id,
            signal_type="interest_signal",
            scope="creative",
            dimension_key=signal_key,
            value={"artifact_id": artifact_id, "version": version, "title": title},
            statement=f"自由创作作品：《{title}》",
            confidence=0.8,
            observed_from=ts,
            last_evaluated_at=ts,
            status="active",
        )
        db.add(existing)
    else:
        existing.value = {"artifact_id": artifact_id, "version": version, "title": title}
        existing.statement = f"自由创作作品：《{title}》"
        existing.last_evaluated_at = ts
    db.flush()
    return {"event_id": event.id, "signal_id": existing.id}


def consume_pending_creation_footprints(db: Session, *, limit: int = 100) -> int:
    """Process pending CreationFootprintRecorded.v1 OutboxEvents idempotently."""
    pending = (
        db.query(OutboxEvent)
        .filter_by(event_type="CreationFootprintRecorded.v1", status="pending")
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    processed = 0
    for row in pending:
        payload = row.payload or {}
        ward_id = payload.get("ward_id")
        artifact_id = payload.get("artifact_id")
        version = int(payload.get("version") or 1)
        title = str(payload.get("title") or "未命名作品")
        if ward_id and artifact_id:
            ingest_creation_interest_signal(
                db,
                ward_id=str(ward_id),
                artifact_id=str(artifact_id),
                version=version,
                title=title,
                occurred_at=row.created_at,
            )
        row.status = "processed"
        processed += 1
    db.flush()
    return processed


def list_evening_creation_footprints(
    db: Session,
    *,
    ward_id: str,
    local_date: date,
    tz_name: str = "Asia/Shanghai",
) -> list[dict]:
    """Evaluation read-only projection of saved Ward creative works for a local day."""
    tz = ZoneInfo(tz_name)
    start_utc = datetime.combine(local_date, time.min, tz).astimezone(timezone.utc)
    end_utc = datetime.combine(local_date, time.max, tz).astimezone(timezone.utc)
    rows = (
        db.query(CreativeWork)
        .filter(
            CreativeWork.ward_id == ward_id,
            CreativeWork.saved.is_(True),
            CreativeWork.updated_at >= start_utc,
            CreativeWork.updated_at <= end_utc,
        )
        .order_by(CreativeWork.updated_at.desc())
        .all()
    )
    return [
        {
            "artifact_id": row.id,
            "title": row.title,
            "version": row.branch[row.cursor],
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]
