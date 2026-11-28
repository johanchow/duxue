"""Study session rollover and explicit task completion."""

from datetime import date
from fastapi import HTTPException
from app.contexts.study.domain.calendar import local_day
from app.infrastructure.persistence.models import (
    Task,
    Ward,
    DailySchedule,
    StudySession,
    StudySessionInterval,
    TutoringSession,
    TutoringProblem,
    OutboxEvent,
    now,
)


class StudyDay:
    def __init__(self, db):
        self.db = db

    def release_unfinished_tasks(self, ward_id: str, today: date) -> int:
        """Return unfinished tasks from a past local day to today's pool and reset cross-day open sessions.

        The old DailySchedule row stays as history. Past-day active/paused StudySessions are
        abandoned and detached so cross-day tasks return to an unscheduled, unstarted state.
        """
        if self.db.query(Ward).filter_by(id=ward_id).with_for_update().first() is None:
            raise HTTPException(404, "学生不存在")
        rows = (
            self.db.query(Task)
            .join(DailySchedule, Task.schedule_id == DailySchedule.id)
            .filter(
                Task.ward_id == ward_id,
                Task.status.in_(["scheduled", "open", "pending"]),
                DailySchedule.schedule_date < today,
            )
            .all()
        )
        released_task_ids = {task.id for task in rows}
        for task in rows:
            task.status = "pool"
            task.schedule_id = None
            task.position = None
        open_sessions = (
            self.db.query(StudySession)
            .filter(
                StudySession.ward_id == ward_id,
                StudySession.status.in_(("active", "paused")),
            )
            .all()
        )
        stale_sessions = [
            s
            for s in open_sessions
            if local_day(s.started_at) < today
            or (s.task_id and s.task_id in released_task_ids)
        ]
        current_time = now()
        for session in stale_sessions:
            for interval in (
                self.db.query(StudySessionInterval)
                .filter_by(study_session_id=session.id, ended_at=None)
                .all()
            ):
                interval.ended_at = current_time
                interval.end_reason = "abandoned"
                interval.active_seconds = 0
            tutor = (
                self.db.query(TutoringSession)
                .filter_by(study_session_id=session.id)
                .one_or_none()
            )
            if tutor is not None:
                for problem in (
                    self.db.query(TutoringProblem)
                    .filter(
                        TutoringProblem.tutoring_session_id == tutor.id,
                        TutoringProblem.status.in_(("open", "submitted")),
                    )
                    .all()
                ):
                    problem.status = "abandoned"
                if tutor.status != "closed":
                    tutor.status = "closed"
                    tutor.closed_at = current_time
            session.status = "abandoned"
            session.ended_at = current_time
            session.completion_reason = "day_rollover"
            session.task_id = None
            session.version += 1
        if rows or stale_sessions:
            self.db.flush()
        return len(rows)

    def declare_completion(
        self, ward_id, task_id, *, session_id=None, active_seconds=None
    ):
        task = self.db.get(Task, task_id)
        changed = (
            task is not None
            and task.ward_id == ward_id
            and task.status not in {"completed", "cancelled"}
        )
        result = self.complete_task(ward_id, task_id)
        if changed:
            self.db.add(
                OutboxEvent(
                    aggregate_type="task",
                    aggregate_id=task_id,
                    event_type="TaskCompletionDeclared.v1",
                    payload={
                        "ward_id": ward_id,
                        "task_id": task_id,
                        "source": "ward_declaration",
                        "version": result.version,
                        "study_session_id": session_id,
                        "active_seconds": active_seconds,
                    },
                )
            )
        return result

    def complete_task(self, ward_id: str, task_id: str) -> Task | None:
        """Mark a task completed. Repeat delivery keeps the terminal status."""
        task = self.db.get(Task, task_id)
        if task is None or task.ward_id != ward_id or task.status == "cancelled":
            return None
        if task.status != "completed":
            task.status = "completed"
            self.db.flush()
        return task
