"""Thin Celery adapters over persistent observation commands."""

from app.application.commands.behavior_observation import ObservationCommands
from app.application.commands.evening_reports import EveningReportCommands
from app.application.commands.help_offers import HelpOfferCommands
from app.infrastructure.ai.behavior_observation import ObservationVision
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import (
    ObservationConsumerInbox,
    ObservationDayRecord,
    OutboxEvent,
    now,
)


def scan_observation_evidence():
    with SessionLocal() as db:
        return ObservationCommands(db, ObservationVision()).scan()


def run_observation_jobs(limit=50):
    with SessionLocal() as db:
        commands = ObservationCommands(db, ObservationVision())
        completed = 0
        while completed < limit and commands.run_next():
            completed += 1
        return completed


def deliver_observation_events(limit=100):
    from datetime import timedelta

    kinds = [
        "ObservationRevisionPublished.v1",
        "HelpOfferReady.v1",
        "HelpOfferPresented.v1",
    ]
    with SessionLocal() as db:
        rows = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type.in_(kinds),
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= now(),
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        count = 0
        for event in rows:
            try:
                with db.begin_nested():
                    payload = event.payload
                    if payload.get("schema_version") != event.event_type:
                        raise ValueError("invalid event schema")
                    key = ("observation-downstream", event.id)
                    if db.get(ObservationConsumerInbox, key) is None:
                        if event.event_type == "ObservationRevisionPublished.v1":
                            day = db.get(ObservationDayRecord, payload["day_id"])
                            if day and day.ward_id == payload["ward_id"]:
                                HelpOfferCommands(db).consider(day.id)
                                EveningReportCommands(db).publish(
                                    day.ward_id, day.local_date
                                )
                        # Support is delivered by foreground polling; these events
                        # acknowledge the durable lifecycle without replaying speech.
                        db.add(
                            ObservationConsumerInbox(
                                consumer=key[0],
                                event_id=key[1],
                                ward_id=payload["ward_id"],
                            )
                        )
                    event.status = "published"
                    event.published_at = now()
                count += 1
            except Exception:
                event.attempts += 1
                event.status = "failed" if event.attempts >= 8 else "pending"
                event.last_error = "observation_delivery_failed"
                event.available_at = now() + timedelta(
                    seconds=min(600, 5 * 2**event.attempts)
                )
        db.commit()
        return count


def publish_evening_deadlines():
    with SessionLocal() as db:
        return EveningReportCommands(db).deadlines()


def reconcile_evening_sources():
    """Teaching has no version notification yet: reconcile its current daily Query."""
    from zoneinfo import ZoneInfo

    from app.infrastructure.persistence.models import ObservationSettings

    with SessionLocal() as db:
        settings = db.query(ObservationSettings).filter_by(report_enabled=True).all()
        for setting in settings:
            day = now().astimezone(ZoneInfo(setting.timezone)).date()
            EveningReportCommands(db).publish(setting.ward_id, day)
            db.commit()
        return len(settings)
