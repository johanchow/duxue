"""Pure, deterministic Planning rules; no persistence, transport or model calls."""
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PLAN_TIME_ZONE = ZoneInfo("Asia/Shanghai")
POOL = "pool"
SCHEDULED = "scheduled"
COMPLETED = "completed"
CANCELLED = "cancelled"
# Rows written before the status table still use these names until migrated.
_LEGACY_POOL = {"open", "pending"}


def local_plan_date(current: datetime | None = None):
    """Ward-facing calendar day. Persisted timestamps stay UTC."""
    moment = current or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(PLAN_TIME_ZONE).date()


def can_schedule(status: str) -> bool:
    return status in {POOL, SCHEDULED, *_LEGACY_POOL}


class TaskReferenceResolver:
    @staticmethod
    def normalise(value):
        return ''.join(c for c in unicodedata.normalize('NFKC', str(value or '')).casefold()
                       if not c.isspace() and c not in '-_·,，。！？!?（）()')

    @classmethod
    def resolve(cls, reference, candidates):
        name = cls.normalise(reference)
        exact = [t for t in candidates if name and cls.normalise(t['title']) == name]
        return exact or [t for t in candidates if name and cls.normalise(t['title']).startswith(name)]

    @classmethod
    def title_conflicts(cls, title, candidates, *, exclude_ids=()):
        """Find canonical-equivalent titles; never use prefix or fuzzy matching."""
        canonical = cls.normalise(title)
        excluded = set(exclude_ids)
        return [candidate for candidate in candidates
                if candidate.get('id') not in excluded
                and canonical
                and cls.normalise(candidate.get('title')) == canonical]


class SchedulingService:
    @staticmethod
    def instant(value):
        result = datetime.fromisoformat(value)
        return result.replace(tzinfo=ZoneInfo('Asia/Shanghai')) if result.tzinfo is None else result

    @classmethod
    def validate_schedule(cls, items):
        conflicts = []
        slots = [i for i in items if i.get('start_at') and i.get('end_at') and not i.get('deferred')]
        for index, item in enumerate(slots):
            for other in slots[index + 1:]:
                if (cls.instant(item['start_at']) < cls.instant(other['end_at'])
                        and cls.instant(other['start_at']) < cls.instant(item['end_at'])):
                    conflicts.append({'code': 'time_overlap',
                                      'task_ids': [item['assignment_id'], other['assignment_id']],
                                      'intervals': [[item['start_at'], item['end_at']],
                                                    [other['start_at'], other['end_at']]]})
        if sum(i['planned_minutes'] for i in slots) > 480:
            conflicts.append({'code': 'daily_capacity', 'task_ids': [i['assignment_id'] for i in slots]})
        return conflicts
