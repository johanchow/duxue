"""Read-only duration evidence for a Ward's current planning decision."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from statistics import median

from sqlalchemy.orm import Session

from app.contexts.planning.domain.scheduling import PLAN_TIME_ZONE, TaskReferenceResolver
from app.infrastructure.persistence.models import StudySession, Task


class DurationSuggestionQuery:
    def __init__(self, db: Session):
        self.db = db

    def for_title(self, *, ward_id: str, title: str, plan_date: date,
                  exclude_task_id: str | None = None) -> dict | None:
        canonical = TaskReferenceResolver.normalise(title)
        if not canonical:
            return None
        first_day = plan_date - timedelta(days=14)
        lower = datetime.combine(first_day, time.min, PLAN_TIME_ZONE).astimezone(timezone.utc)
        upper = datetime.combine(plan_date + timedelta(days=1), time.min, PLAN_TIME_ZONE).astimezone(timezone.utc)
        rows = (
            self.db.query(StudySession, Task)
            .join(Task, StudySession.task_id == Task.id)
            .filter(StudySession.ward_id == ward_id, Task.ward_id == ward_id,
                    StudySession.status == "completed", StudySession.ended_at >= lower,
                    StudySession.ended_at < upper)
            .order_by(StudySession.ended_at.desc())
            .all()
        )
        by_task: dict[str, int] = {}
        for session, task in rows:
            if task.id == exclude_task_id or task.id in by_task:
                continue
            if TaskReferenceResolver.normalise(task.title) != canonical:
                continue
            seconds = session.active_seconds
            if not isinstance(seconds, int) or not 0 < seconds <= 480 * 60:
                continue
            by_task[task.id] = seconds
        if len(by_task) < 3:
            return None
        minutes = median(by_task.values()) / 60
        suggested = max(1, min(480, int((minutes + 2.5) // 5) * 5))
        return {
            "suggested_minutes": suggested,
            "sample_count": len(by_task),
            "actual_min_minutes": max(1, round(min(by_task.values()) / 60)),
            "actual_max_minutes": max(1, round(max(by_task.values()) / 60)),
            "actual_median_minutes": max(1, round(minutes)),
            "basis": "同名任务近15天实际用时",
            "fingerprint": sha256(json.dumps(sorted(by_task.items())).encode()).hexdigest(),
        }
