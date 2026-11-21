"""Study owns interruptions independently of a task, Sprint, or chat thread."""

from datetime import timedelta

from fastapi import HTTPException

from app.infrastructure.persistence.models import (
    HelpOfferRecord,
    OutboxEvent,
    QuietCommand,
    QuietPeriod,
)


def latest_period(db, ward_id):
    return (
        db.query(QuietPeriod)
        .populate_existing()
        .filter_by(ward_id=ward_id)
        .order_by(QuietPeriod.version.desc())
        .first()
    )


def quiet_boundary(db, ward_id):
    from .behavior_observation import utc

    period = latest_period(db, ward_id)
    return utc(period.ended_at or period.scheduled_until) if period else None


def excluded_slots(db, ward_id, start, end):
    from .behavior_observation import utc

    periods = (
        db.query(QuietPeriod)
        .filter(
            QuietPeriod.ward_id == ward_id,
            QuietPeriod.starts_at < end,
            QuietPeriod.scheduled_until > start,
        )
        .all()
    )
    slots = []
    cursor = start
    while cursor < end:
        if any(
            cursor < utc(p.ended_at or p.scheduled_until)
            and utc(p.starts_at) < cursor + timedelta(seconds=15)
            for p in periods
        ):
            slots.append(cursor.isoformat())
        cursor += timedelta(seconds=15)
    return slots


def change_quiet(db, ward_id, command_id, action, seconds, now, expected_version=None):
    from .behavior_observation import digest, lock, utc

    if (
        action not in {"start", "extend", "end"}
        or (action == "end" and seconds is not None)
        or (action != "end" and (type(seconds) is not int or not 1 <= seconds <= 86400))
    ):
        raise HTTPException(422, "invalid quiet period")
    lock(db, f"observation-ward:{ward_id}")
    key = digest([action, seconds, expected_version])
    receipt = db.get(QuietCommand, (ward_id, command_id))
    if receipt:
        if receipt.request_digest != key:
            raise HTTPException(409, "command identity conflict")
        return receipt.result
    period = latest_period(db, ward_id)
    version = period.version if period else 0
    if expected_version is not None and expected_version != version:
        raise HTTPException(409, "quiet period changed")
    active = bool(
        period and period.ended_at is None and utc(period.scheduled_until) > now
    )
    if action == "extend" and not active:
        raise HTTPException(409, "休息时段已经结束")
    if action != "end" or active:
        version += 1
        if action == "end":
            period.ended_at = now
        else:
            base = utc(period.scheduled_until) if action == "extend" else now
            until = base + timedelta(seconds=seconds)
            if until - now > timedelta(days=1):
                raise HTTPException(422, "休息时长最多为24小时")
            if active:
                period.scheduled_until = max(utc(period.scheduled_until), until)
            else:
                period = QuietPeriod(
                    ward_id=ward_id, starts_at=now, scheduled_until=until
                )
                db.add(period)
        period.version = version
        db.flush()
        event_type = "ObservationQuietPeriodChanged.v1"
        db.add(
            OutboxEvent(
                aggregate_type="study_observation_quiet",
                aggregate_id=period.id,
                event_type=event_type,
                payload={
                    "schema_version": event_type,
                    "ward_id": ward_id,
                    "ward_version": version,
                    "period_id": period.id,
                    "starts_at": utc(period.starts_at).isoformat(),
                    "effective_until": utc(
                        period.ended_at or period.scheduled_until
                    ).isoformat(),
                },
            )
        )
        for offer in (
            db.query(HelpOfferRecord)
            .filter_by(ward_id=ward_id)
            .filter(HelpOfferRecord.status.in_(("ready", "presented")))
            .all()
        ):
            offer.status, offer.closed_reason = "expired", "quiet_period"
            offer.version += 1
    active = bool(
        period and period.ended_at is None and utc(period.scheduled_until) > now
    )
    result = {
        "active": active,
        "ward_version": version,
        "period_id": period.id if period else None,
        "effective_until": utc(period.scheduled_until).isoformat() if active else None,
    }
    db.add(
        QuietCommand(
            ward_id=ward_id,
            command_id=command_id,
            period_id=result["period_id"],
            action=action,
            request_digest=key,
            result=result,
            ward_version=version,
        )
    )
    db.flush()
    return result
