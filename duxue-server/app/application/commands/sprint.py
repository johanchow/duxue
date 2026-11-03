"""Ward-owned sprint commands. Caller owns the transaction; Ward lock serializes commands."""

import hashlib
import json
from datetime import datetime, timedelta, time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.contexts.planning.domain.scheduling import local_plan_date, PLAN_TIME_ZONE
from app.contexts.study.domain.sprint import running_seconds, utc
from app.infrastructure.persistence.models import (
    Sprint,
    SprintCommand,
    StudySession,
    Task,
    Ward,
    now,
)


class SprintService:
    def __init__(self, db: Session, *, moment: datetime | None = None):
        self.db, self.at = db, utc(moment or now())

    def _lock(self, ward_id):
        if (
            self.db.query(Ward).filter_by(id=ward_id).with_for_update().one_or_none()
            is None
        ):
            raise HTTPException(404, "学生不存在")

    def _close_interval(self, row, reason, *, at=None):
        stop = utc(at or self.at)
        if row.active_since:
            row.intervals = [
                *(row.intervals or []),
                {
                    "start": utc(row.active_since).isoformat(),
                    "end": stop.isoformat(),
                    "reason": reason,
                },
            ]
            row.elapsed_seconds = running_seconds(
                elapsed=row.elapsed_seconds,
                active_since=row.active_since,
                at=stop,
                target=row.target_seconds,
            )
        row.active_since = None

    def _sync(self, ward_id):
        for row in (
            self.db.query(Sprint)
            .populate_existing()
            .filter_by(ward_id=ward_id)
            .filter(Sprint.status.in_(("active", "paused", "ready")))
            .with_for_update()
            .all()
        ):
            origin = row.started_at or row.planned_start_at or row.created_at
            boundary = datetime.combine(
                local_plan_date(origin) + timedelta(days=1), time.min, PLAN_TIME_ZONE
            )
            deadline = (
                utc(row.active_since)
                + timedelta(seconds=row.target_seconds - row.elapsed_seconds)
                if row.active_since
                else None
            )
            if row.status == "active" and deadline <= self.at and deadline <= boundary:
                self._close_interval(row, "elapsed", at=deadline)
                row.status, row.ended_at, row.end_reason = (
                    "elapsed",
                    deadline,
                    "timebox_elapsed",
                )
            elif local_plan_date(origin) < local_plan_date(self.at):
                self._close_interval(row, "day_rollover", at=boundary)
                row.status, row.ended_at, row.end_reason = (
                    "ended",
                    boundary,
                    "day_rollover",
                )
            self.db.flush()

    def view(self, row):
        if row is None:
            return None
        elapsed = running_seconds(
            elapsed=row.elapsed_seconds,
            active_since=row.active_since,
            at=self.at,
            target=row.target_seconds,
        )
        return {
            "id": row.id,
            "topic": row.topic,
            "task_id": row.task_id,
            "study_session_id": row.study_session_id,
            "status": row.status,
            "version": row.version,
            "target_seconds": row.target_seconds,
            "elapsed_seconds": elapsed,
            "remaining_seconds": row.target_seconds - elapsed,
            "server_now": self.at.isoformat(),
            "started_at": utc(row.started_at).isoformat() if row.started_at else None,
            "planned_start_at": utc(row.planned_start_at).isoformat()
            if row.planned_start_at
            else None,
            "end_reason": row.end_reason,
        }

    def current(self, ward_id):
        self._lock(ward_id)
        self._sync(ward_id)
        row = (
            self.db.query(Sprint)
            .populate_existing()
            .filter_by(ward_id=ward_id)
            .filter(Sprint.status.in_(("active", "paused")))
            .one_or_none()
        )
        ready = (
            self.db.query(Sprint)
            .populate_existing()
            .filter_by(ward_id=ward_id, status="ready")
            .first()
        )
        notice = (
            self.db.query(Sprint)
            .populate_existing()
            .filter(
                Sprint.ward_id == ward_id,
                Sprint.status == "elapsed",
                Sprint.notice_claimed.is_(False),
                Sprint.ended_at >= self.at - timedelta(seconds=60),
            )
            .order_by(Sprint.ended_at.desc())
            .first()
        )
        if (
            notice is None
            and ready
            and ready.planned_start_at
            and not ready.notice_claimed
        ):
            if (
                self.at - timedelta(seconds=60)
                <= utc(ready.planned_start_at)
                <= self.at
            ):
                notice = ready
        return {
            "sprint": self.view(row),
            "ready": self.view(ready),
            "notice": self.view(notice),
        }

    def execute(
        self,
        ward_id,
        command_id,
        action,
        *,
        sprint_id=None,
        expected_version=None,
        topic=None,
        target_minutes=None,
        task_id=None,
        study_session_id=None,
        planned_start_at=None,
    ):
        self._lock(ward_id)
        if planned_start_at and planned_start_at.tzinfo is None:
            planned_start_at = planned_start_at.replace(tzinfo=PLAN_TIME_ZONE)
        data = {
            "action": action,
            "sprint_id": sprint_id,
            "expected_version": expected_version,
            "topic": topic,
            "target_minutes": target_minutes,
            "task_id": task_id,
            "study_session_id": study_session_id,
            "planned_start_at": planned_start_at.isoformat()
            if planned_start_at
            else None,
        }
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
        previous = (
            self.db.query(SprintCommand)
            .filter_by(ward_id=ward_id, command_id=command_id)
            .one_or_none()
        )
        if previous:
            if previous.fingerprint != fingerprint:
                raise HTTPException(409, "同一操作标识不能用于不同命令")
            return previous.result
        self._sync(ward_id)
        if action in {"create", "prepare"}:
            if (
                not isinstance(topic, str)
                or not topic.strip()
                or len(topic.strip()) > 300
            ):
                raise HTTPException(422, "请说明这轮挑战的主题")
            if (
                isinstance(target_minutes, bool)
                or not isinstance(target_minutes, int)
                or not 1 <= target_minutes <= 180
            ):
                raise HTTPException(422, "挑战时长需为1至180分钟")
            if task_id:
                task = self.db.get(Task, task_id)
                if (
                    task is None
                    or task.ward_id != ward_id
                    or task.status in {"cancelled", "completed"}
                ):
                    raise HTTPException(404, "挑战关联任务不存在")
            if study_session_id:
                session = self.db.get(StudySession, study_session_id)
                if (
                    session is None
                    or session.ward_id != ward_id
                    or (task_id and session.task_id != task_id)
                ):
                    raise HTTPException(404, "挑战关联会话不存在")
            if (
                action == "create"
                and planned_start_at
                and utc(planned_start_at) > self.at
            ):
                raise HTTPException(409, "未来约定不能自动开始挑战")
            row = Sprint(
                ward_id=ward_id,
                topic=topic.strip(),
                target_seconds=target_minutes * 60,
                task_id=task_id,
                study_session_id=study_session_id,
                status="ready",
                planned_start_at=planned_start_at,
                created_at=self.at,
            )
            self.db.add(row)
            self.db.flush()
        else:
            row = (
                self.db.query(Sprint)
                .populate_existing()
                .filter_by(id=sprint_id, ward_id=ward_id)
                .with_for_update()
                .one_or_none()
            )
            if row is None:
                raise HTTPException(404, "挑战不存在")
            if expected_version != row.version:
                raise HTTPException(409, "挑战状态已变化，请刷新")
        if action in {"create", "start", "resume"}:
            expected = {"ready"} if action != "resume" else {"paused"}
            if row.status not in expected:
                raise HTTPException(409, "本轮不能开始或继续")
            if (
                self.db.query(Sprint)
                .populate_existing()
                .filter(
                    Sprint.ward_id == ward_id,
                    Sprint.id != row.id,
                    Sprint.status.in_(("active", "paused")),
                )
                .first()
            ):
                raise HTTPException(409, "请先结束已有挑战，再开启新一轮")
            row.status, row.active_since = "active", self.at
            row.started_at = row.started_at or self.at
        elif action == "pause":
            if row.status != "active":
                raise HTTPException(409, "本轮未在计时")
            self._close_interval(row, "paused")
            row.status = "paused"
        elif action in {"end", "cancel"}:
            if row.status not in {"ready", "active", "paused"}:
                raise HTTPException(409, "本轮已结束")
            self._close_interval(row, action)
            row.status, row.ended_at, row.end_reason = (
                ("cancelled" if action == "cancel" else "ended"),
                self.at,
                action,
            )
        elif action == "claim_notice":
            if (
                row.status not in {"elapsed", "ready"}
                or row.notice_claimed
                or (
                    row.status == "ready"
                    and (
                        not row.planned_start_at or utc(row.planned_start_at) > self.at
                    )
                )
            ):
                raise HTTPException(409, "本轮反馈已处理")
            row.notice_claimed = True
        elif action != "prepare":
            raise HTTPException(422, "未知挑战操作")
        self.db.flush()
        result = {"sprint": self.view(row)}
        self.db.add(
            SprintCommand(
                ward_id=ward_id,
                command_id=command_id,
                fingerprint=fingerprint,
                result=result,
            )
        )
        self.db.flush()
        return result
