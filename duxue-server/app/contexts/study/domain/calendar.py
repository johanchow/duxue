"""Ward-facing calendar days use Shanghai time; persisted timestamps are UTC."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

WARD_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def local_day(current: datetime | None = None):
    """Ward-facing calendar day. Persisted timestamps stay UTC."""
    moment = current or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(WARD_TIME_ZONE).date()


def local_instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=WARD_TIME_ZONE) if result.tzinfo is None else result
