"""Load one coherent published day/revision pair for authorized consumers."""

from dataclasses import dataclass
from datetime import date, datetime

from app.infrastructure.persistence.models import (
    ObservationDayRecord as Day,
)
from app.infrastructure.persistence.models import (
    ObservationRevisionRecord as Revision,
)


@dataclass(frozen=True)
class PublishedDay:
    id: str
    ward_id: str
    local_date: date
    revision: int
    generated_at: datetime
    snapshot: dict


def published_day(db, *, ward_id, day_id=None, local_date=None):
    query = (
        db.query(
            Day.id,
            Day.ward_id,
            Day.local_date,
            Day.revision,
            Revision.created_at,
            Revision.snapshot,
        )
        .join(
            Revision, (Revision.day_id == Day.id) & (Revision.revision == Day.revision)
        )
        .filter(Day.ward_id == ward_id)
    )
    if day_id is not None:
        query = query.filter(Day.id == day_id)
    elif local_date is not None:
        query = query.filter(Day.local_date == local_date)
    else:
        raise ValueError("day_id or local_date required")
    row = query.one_or_none()
    return PublishedDay(*row) if row else None


def observation_owner(db, day_id):
    return db.query(Day.ward_id).filter(Day.id == day_id).scalar()
