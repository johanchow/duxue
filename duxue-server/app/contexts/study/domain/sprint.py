"""A sprint measures an authorized timebox, never concentration or task completion."""

from datetime import datetime, timezone


def utc(moment: datetime) -> datetime:
    return (
        moment.replace(tzinfo=timezone.utc)
        if moment.tzinfo is None
        else moment.astimezone(timezone.utc)
    )


def running_seconds(
    *, elapsed: int, active_since: datetime | None, at: datetime, target: int
) -> int:
    extra = (
        max(0, int((utc(at) - utc(active_since)).total_seconds()))
        if active_since
        else 0
    )
    return min(target, elapsed + extra)
