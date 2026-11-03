"""Explicit task execution, with server-owned interval timing and Ward declarations."""

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.contexts.study.domain.sprint import utc
from app.infrastructure.persistence.models import (
    Task,
    Ward,
    StudySession,
    StudySessionInterval,
    OutboxEvent,
    now,
)


class TaskExecutionService:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, ward_id, task_id, action):
        self.db.query(Ward).filter_by(id=ward_id).with_for_update().one()
        task = self.db.get(Task, task_id)
        if task is None or task.ward_id != ward_id or task.status == "cancelled":
            raise HTTPException(404, "任务不存在")
        session = (
            self.db.query(StudySession)
            .filter_by(ward_id=ward_id, task_id=task_id)
            .filter(StudySession.status.in_(("active", "paused")))
            .first()
        )
        if action == "time":
            sessions = (
                self.db.query(StudySession)
                .filter_by(ward_id=ward_id, task_id=task_id)
                .all()
            )
            seconds = sum(self._seconds(s) for s in sessions)
            return {
                "task_id": task_id,
                "active_seconds": seconds if sessions else None,
                "basis": "explicit_session_intervals" if sessions else "unknown",
            }
        before_version = session.version if session else None
        if task.status == "completed":
            if action == "complete":
                return {"task_id": task_id, "status": "completed"}
            raise HTTPException(409, "任务已声明完成")
        if action in {"start", "resume"}:
            # Starting a different task is an explicit switch, not parallel timing.
            for other in (
                self.db.query(StudySession)
                .filter_by(ward_id=ward_id, status="active")
                .all()
            ):
                if session is None or other.id != session.id:
                    self._close(other, "paused")
                    other.status, other.version = "paused", other.version + 1
                    publish_learning_fact(
                        self.db,
                        ward_id=ward_id,
                        event_type="study_session.paused",
                        source_type="study_session",
                        source_id=other.id,
                        source_version=other.version,
                        payload={
                            "task_id": other.task_id,
                            "active_seconds": other.active_seconds,
                        },
                    )
            if session is None:
                session = StudySession(ward_id=ward_id, task_id=task_id)
                self.db.add(session)
                self.db.flush()
                self.db.add(StudySessionInterval(study_session_id=session.id))
            elif session.status == "paused":
                session.status, session.version = "active", session.version + 1
                session.last_activity_at = now()
                self.db.add(StudySessionInterval(study_session_id=session.id))
        elif action == "pause":
            if session and session.status == "active":
                self._close(session, "paused")
                session.status, session.version = "paused", session.version + 1
        elif action in {"end", "complete"}:
            if session:
                self._close(session, action)
                session.status = "completed" if action == "complete" else "abandoned"
                session.completion_reason = (
                    "ward_finished" if action == "complete" else "ward_stopped"
                )
                session.ended_at, session.version = now(), session.version + 1
            if action == "complete":
                from app.application.workflows.planning_domain_service import (
                    PlanningDomainService,
                )

                PlanningDomainService(self.db).declare_completion(
                    ward_id,
                    task_id,
                    session_id=session.id if session else None,
                    active_seconds=session.active_seconds if session else None,
                )
        else:
            raise HTTPException(422, "未知执行操作")
        self.db.flush()
        if session and (before_version is None or session.version != before_version):
            suffix = {
                "start": "started",
                "resume": "resumed",
                "pause": "paused",
                "end": "abandoned",
                "complete": "completed",
            }[action]
            publish_learning_fact(
                self.db,
                ward_id=ward_id,
                event_type="study_session." + suffix,
                source_type="study_session",
                source_id=session.id,
                source_version=session.version,
                payload={"task_id": task_id, "active_seconds": session.active_seconds},
            )
            if action == "complete":
                self.db.add(
                    OutboxEvent(
                        aggregate_type="study_session",
                        aggregate_id=session.id,
                        event_type="StudySessionCompleted.v1",
                        payload={
                            "ward_id": ward_id,
                            "task_id": task_id,
                            "session_id": session.id,
                            "version": session.version,
                        },
                    )
                )
        return {
            "task_id": task_id,
            "status": task.status,
            "session": None
            if session is None
            else {
                "id": session.id,
                "status": session.status,
                "active_seconds": self._seconds(session),
            },
        }

    def _seconds(self, session):
        intervals = (
            self.db.query(StudySessionInterval)
            .filter_by(study_session_id=session.id)
            .all()
        )
        if not intervals:
            return session.active_seconds
        return sum(
            max(0, int((utc(i.ended_at or now()) - utc(i.started_at)).total_seconds()))
            for i in intervals
        )

    def _close(self, session, reason):
        session.last_activity_at = now()
        if reason == "paused":
            session.pause_count += 1
        for interval in (
            self.db.query(StudySessionInterval)
            .filter_by(study_session_id=session.id, ended_at=None)
            .all()
        ):
            interval.ended_at, interval.end_reason = now(), reason
            interval.active_seconds = max(
                0,
                int(
                    (utc(interval.ended_at) - utc(interval.started_at)).total_seconds()
                ),
            )
        self.db.flush()
        session.active_seconds = self._seconds(session)
