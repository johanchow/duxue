"""Idempotent consumers and projections for CreationFootprintRecorded.v1.

Strictly isolates Ward creative exploration into Interest Signals (Memory) and
evening creation footprints (Evaluation) without touching academic mastery.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from sqlalchemy.orm import Session

from app.application.commands.behavior_observation import lock, utc
from app.application.commands.memory import _record_learning_evidence
from app.infrastructure.persistence.models import (
    DerivedSignal,
    OutboxEvent,
    ObservationSettings,
    now,
)


class Footprint(BaseModel):
    artifact_id: UUID
    ward_id: UUID
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=80)


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
    elif version > existing.value["version"]:
        existing.value = {
            "artifact_id": artifact_id,
            "version": version,
            "title": title,
        }
        existing.statement = f"自由创作作品：《{title}》"
        existing.last_evaluated_at = ts
    db.flush()
    return {"event_id": event.id, "signal_id": existing.id}


def consume_pending_creation_footprints(db: Session, *, limit: int = 100) -> int:
    """Process pending CreationFootprintRecorded.v1 OutboxEvents idempotently."""
    pending = (
        db.query(OutboxEvent)
        .filter_by(event_type="CreationFootprintRecorded.v1", status="pending")
        .filter(OutboxEvent.available_at <= now())
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    # Stabilize lock order when workers consume different versions concurrently.
    ward_keys = {
        row.payload.get("ward_id")
        for row in pending
        if isinstance(row.payload, dict) and isinstance(row.payload.get("ward_id"), str)
    }
    for key in sorted(ward_keys):
        lock(db, f"observation-ward:{key}")
    processed = 0
    for row in pending:
        try:
            with db.begin_nested():
                footprint = Footprint.model_validate(row.payload)
                ward_id = str(footprint.ward_id)
                ingest_creation_interest_signal(
                    db,
                    ward_id=ward_id,
                    artifact_id=str(footprint.artifact_id),
                    version=footprint.version,
                    title=footprint.title,
                    occurred_at=row.created_at,
                )
                setting = db.get(ObservationSettings, ward_id)
                if setting and setting.report_enabled:
                    from app.application.commands.evening_reports import (
                        EveningReportCommands,
                    )

                    day = (
                        utc(row.created_at)
                        .astimezone(ZoneInfo(setting.timezone))
                        .date()
                    )
                    EveningReportCommands(db).publish(ward_id, day)
                row.status = "published"
                row.published_at = now()
            processed += 1
        except Exception:
            row.last_error = "creation_footprint_delivery_failed"
            row.available_at = now() + timedelta(
                seconds=min(600, 5 * 2 ** min(row.attempts, 7))
            )
            if row.attempts >= 7:
                row.status = "failed"
        row.attempts += 1
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
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type == "CreationFootprintRecorded.v1",
            OutboxEvent.payload["ward_id"].as_string() == ward_id,
            OutboxEvent.created_at >= start_utc,
            OutboxEvent.created_at <= end_utc,
        )
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
        .all()
    )
    works = {}
    for row in rows:
        try:
            payload = Footprint.model_validate(row.payload).model_dump(mode="json")
        except ValidationError:
            continue
        works.setdefault(
            payload["artifact_id"],
            {
                "artifact_id": payload["artifact_id"],
                "title": payload["title"],
                "version": payload["version"],
                "updated_at": utc(row.created_at).isoformat(),
            },
        )
    return list(works.values())
