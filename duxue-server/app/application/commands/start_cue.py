"""到点邀请的应用用例。现场缺席时不调用视觉分类，文案使用策略兜底句。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.contexts.planning.domain.scheduling import SchedulingService, local_plan_date
from app.contexts.study.domain.start_cue import (
    OPEN_STATUSES,
    CueDecision,
    SceneRead,
    StartCueError,
    StartCuePolicy,
    admits,
    fallback_text,
)
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.persistence.models import (
    DailySchedule,
    StartCueRecord,
    StudySession,
    StudySessionInterval,
    Task,
    now,
)

ABSENT_SCENE = SceneRead("no_observation", "no_frames")
_SNOOZE = timedelta(minutes=10)


class StartCueService:
    def __init__(self, db: Session):
        self.db = db

    def sync(self, ward_id: str, *, moment: datetime | None = None, scene: SceneRead | None = None) -> dict:
        current = moment or now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        scene = scene or ABSENT_SCENE
        schedule = self._schedule(ward_id, local_plan_date(current))
        cue = self._open_cue(ward_id)
        if schedule is None or schedule.status != "confirmed":
            if cue is not None:
                self._expire(cue)
            return self._with_notifications(ward_id, current, {"status": "none"})
        if cue is not None and (cue.schedule_id != schedule.id or cue.schedule_version != schedule.version):
            self._expire(cue)
            cue = None
        due = self._due_items(schedule, ward_id, current)
        if cue is not None and self._task_in_progress(ward_id, cue.due_task_id):
            self._accept(cue, "start_due_task")
            cue = None
        if not due:
            if cue is not None and current >= cue.end_at and cue.status != "presented":
                self._expire(cue)
                cue = None
            return self._with_notifications(ward_id, current, self._view(cue))
        target = due[-1]
        earlier = self._earlier_unstarted(schedule, ward_id, current, target["start"])
        if cue is not None and cue.due_task_id != target["task_id"]:
            self._supersede(cue)
            cue = None
        if cue is None:
            cue = self._open(ward_id, schedule, target, earlier)
        else:
            cue.earlier_task_ids = [item["task_id"] for item in earlier]
        if cue.snoozed_until is not None and current < cue.snoozed_until:
            return self._with_notifications(ward_id, current, {"status": "none"})
        if current >= cue.end_at and cue.status != "presented":
            self._expire(cue)
            return self._with_notifications(ward_id, current, {"status": "none"})
        other = self._other_session(ward_id, target["task_id"])
        decision = StartCuePolicy.decide(
            other_session=other is not None,
            scene=scene,
            snooze_count=cue.snooze_count,
            past_end=False,
        )
        self._apply(cue, target, earlier, other, scene, decision)
        return self._with_notifications(ward_id, current, self._view(cue))

    def _with_notifications(self, ward_id: str, current: datetime, view: dict) -> dict:
        schedule = self._schedule(ward_id, local_plan_date(current))
        view["notifications"] = self._upcoming(ward_id, schedule, current)
        return view

    def _upcoming(self, ward_id: str, schedule: DailySchedule | None, current: datetime) -> list[dict]:
        if schedule is None or schedule.status != "confirmed":
            return []
        notes = []
        last_end = None
        for item in self._slots(schedule, ward_id):
            if last_end is None or item["end"] > last_end:
                last_end = item["end"]
            if item["start"] > current and not self._task_in_progress(ward_id, item["task_id"]):
                notes.append({
                    "id": f"start:{item['task_id']}",
                    "fire_at": item["start"].isoformat(),
                    "title": f"{item['title']}到点了",
                    "body": f"{item['title']} {item['start_label']} 到了。打开读学可以开始。",
                    "kind": "start",
                })
        session = (
            self.db.query(StudySession)
            .filter(StudySession.ward_id == ward_id, StudySession.status == "active", StudySession.task_id.is_not(None))
            .order_by(StudySession.started_at.desc())
            .first()
        )
        if session is not None and session.task_id:
            task = self.db.get(Task, session.task_id)
            started = session.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if task is not None and task.planned_minutes:
                fire = started + timedelta(minutes=int(task.planned_minutes))
                if fire > current:
                    notes.append({
                        "id": f"rest:{session.id}",
                        "fire_at": fire.isoformat(),
                        "title": "可以休息一下",
                        "body": f"{task.title}的这段时间到了。可以暂停，也可以继续。",
                        "kind": "rest",
                    })
        if last_end is not None and last_end > current:
            notes.append({
                "id": f"day:{schedule.id}",
                "fire_at": last_end.isoformat(),
                "title": "可以总结今天",
                "body": "今天计划的时间到了。打开读学，先说说自己的感受。",
                "kind": "day_review",
            })
        return notes

    def _slots(self, schedule: DailySchedule, ward_id: str) -> list[dict]:
        rows = []
        for item in schedule.items or []:
            task_id = item.get("assignment_id")
            start_raw = item.get("start_at")
            if not task_id or not start_raw:
                continue
            task = self.db.get(Task, task_id)
            if task is None or task.ward_id != ward_id:
                continue
            start = SchedulingService.instant(start_raw).astimezone(timezone.utc)
            end_raw = item.get("end_at")
            if end_raw:
                end = SchedulingService.instant(end_raw).astimezone(timezone.utc)
            else:
                end = start + timedelta(minutes=int(item.get("planned_minutes") or task.planned_minutes or 0))
            rows.append({
                "task_id": task_id,
                "title": task.title,
                "start": start,
                "end": end,
                "start_label": SchedulingService.instant(start_raw).strftime("%H:%M"),
                "planned_minutes": task.planned_minutes,
            })
        return rows

    def act(self, ward_id: str, cue_id: str, command: str, expected_version: int) -> dict:
        cue = self.db.get(StartCueRecord, cue_id)
        if cue is None or cue.ward_id != ward_id:
            raise StartCueError("not_found")
        if cue.version != expected_version:
            raise StartCueError("conflict")
        if cue.status != "presented":
            raise StartCueError("not_presented")
        if not admits(cue.actions or [], command):
            raise StartCueError("action_not_allowed")
        if command == "snooze_once":
            if cue.snooze_count >= 1:
                raise StartCueError("snooze_already_used")
            cue.status = "pending"
            cue.snooze_count += 1
            cue.snoozed_until = now() + _SNOOZE
            cue.text = None
            cue.version += 1
            return {"status": "none"}
        if command == "pause_current_and_start_due":
            if cue.current_session_id:
                session = self.db.get(StudySession, cue.current_session_id)
                if session is not None and session.status == "active":
                    self._pause(session)
            self._start(cue.ward_id, cue.due_task_id)
        elif command == "start_due_task":
            self._start(cue.ward_id, cue.due_task_id)
        self._accept(cue, command)
        return {"status": "accepted", "command": command}

    def note_task_started(self, ward_id: str, task_id: str) -> None:
        cue = self._open_cue(ward_id)
        if cue is not None and cue.due_task_id == task_id:
            self._accept(cue, "start_due_task")

    def _schedule(self, ward_id: str, day) -> DailySchedule | None:
        return (
            self.db.query(DailySchedule)
            .filter_by(ward_id=ward_id, schedule_date=day, status="confirmed")
            .one_or_none()
        )

    def _open_cue(self, ward_id: str) -> StartCueRecord | None:
        return (
            self.db.query(StartCueRecord)
            .filter(StartCueRecord.ward_id == ward_id, StartCueRecord.status.in_(OPEN_STATUSES))
            .one_or_none()
        )

    def _due_items(self, schedule: DailySchedule, ward_id: str, current: datetime) -> list[dict]:
        rows = []
        for item in schedule.items or []:
            task_id = item.get("assignment_id")
            start_raw = item.get("start_at")
            if not task_id or not start_raw:
                continue
            start = SchedulingService.instant(start_raw).astimezone(timezone.utc)
            end_raw = item.get("end_at")
            if end_raw:
                end = SchedulingService.instant(end_raw).astimezone(timezone.utc)
            else:
                end = start + timedelta(minutes=int(item.get("planned_minutes") or 0))
            if not (start <= current < end):
                continue
            task = self.db.get(Task, task_id)
            if task is None or task.ward_id != ward_id or task.status != "scheduled":
                continue
            if self._task_in_progress(ward_id, task_id):
                continue
            rows.append({
                "task_id": task_id,
                "title": task.title,
                "start": start,
                "end": end,
                "start_label": SchedulingService.instant(start_raw).strftime("%H:%M"),
                "planned_minutes": task.planned_minutes,
            })
        rows.sort(key=lambda item: item["start"])
        return rows

    def _earlier_unstarted(self, schedule: DailySchedule, ward_id: str, current: datetime, target_start: datetime) -> list[dict]:
        rows = []
        for item in schedule.items or []:
            task_id = item.get("assignment_id")
            start_raw = item.get("start_at")
            if not task_id or not start_raw:
                continue
            start = SchedulingService.instant(start_raw).astimezone(timezone.utc)
            if not (start <= current and start < target_start):
                continue
            task = self.db.get(Task, task_id)
            if task is None or task.ward_id != ward_id or task.status != "scheduled":
                continue
            if self._task_in_progress(ward_id, task_id):
                continue
            rows.append({"task_id": task_id, "title": task.title, "start": start})
        rows.sort(key=lambda item: item["start"])
        return rows

    def _task_in_progress(self, ward_id: str, task_id: str) -> bool:
        return self._session(ward_id, task_id) is not None

    def _other_session(self, ward_id: str, due_task_id: str) -> StudySession | None:
        return (
            self.db.query(StudySession)
            .filter(StudySession.ward_id == ward_id, StudySession.status.in_(("active", "paused")))
            .filter((StudySession.task_id.is_(None)) | (StudySession.task_id != due_task_id))
            .order_by(StudySession.started_at.desc())
            .first()
        )

    def _session(self, ward_id: str, task_id: str) -> StudySession | None:
        return (
            self.db.query(StudySession)
            .filter_by(ward_id=ward_id, task_id=task_id)
            .filter(StudySession.status.in_(("active", "paused")))
            .first()
        )

    def _open(self, ward_id: str, schedule: DailySchedule, target: dict, earlier: list[dict]) -> StartCueRecord:
        cue = StartCueRecord(
            ward_id=ward_id,
            due_task_id=target["task_id"],
            schedule_id=schedule.id,
            schedule_version=schedule.version,
            start_at=target["start"],
            end_at=target["end"],
            earlier_task_ids=[item["task_id"] for item in earlier],
            status="pending",
        )
        self.db.add(cue)
        self.db.flush()
        return cue

    def _apply(
        self,
        cue: StartCueRecord,
        target: dict,
        earlier: list[dict],
        other: StudySession | None,
        scene: SceneRead,
        decision: CueDecision,
    ) -> None:
        cue.scene_label = scene.label
        cue.gap_reason = scene.gap_reason
        cue.current_session_id = None if other is None else other.id
        cue.earlier_task_ids = [item["task_id"] for item in earlier]
        if decision.disposition == "hold":
            if cue.status != "held":
                cue.status = "held"
                cue.text = None
                cue.actions = []
                cue.version += 1
            return
        if decision.disposition == "expire":
            self._expire(cue)
            return
        other_title = None
        if other is not None and other.task_id:
            other_task = self.db.get(Task, other.task_id)
            other_title = other_task.title if other_task else "当前这项"
        elif other is not None:
            other_title = "当前这项"
        text = fallback_text(
            due_title=target["title"],
            start_label=target["start_label"],
            planned_minutes=target["planned_minutes"],
            other_title=other_title,
            earlier_titles=[item["title"] for item in earlier],
            scene=scene,
        )
        actions = list(decision.actions)
        if cue.status == "presented" and cue.text == text and list(cue.actions or []) == actions:
            return
        cue.status = "presented"
        cue.text = text
        cue.actions = actions
        cue.version += 1

    def _accept(self, cue: StartCueRecord, command: str) -> None:
        cue.status = "accepted"
        cue.version += 1
        cue.actions = [command]

    def _expire(self, cue: StartCueRecord) -> None:
        cue.status = "expired"
        cue.text = None
        cue.version += 1

    def _supersede(self, cue: StartCueRecord) -> None:
        cue.status = "superseded"
        cue.version += 1

    def _start(self, ward_id: str, task_id: str) -> StudySession:
        existing = self._session(ward_id, task_id)
        if existing is not None:
            if existing.status == "paused":
                existing.status = "active"
                existing.version += 1
                self.db.add(StudySessionInterval(study_session_id=existing.id))
            return existing
        session = StudySession(ward_id=ward_id, task_id=task_id, status="active")
        self.db.add(session)
        self.db.flush()
        self.db.add(StudySessionInterval(study_session_id=session.id))
        publish_learning_fact(
            self.db,
            ward_id=ward_id,
            event_type="study_session.started",
            source_type="study_session",
            source_id=session.id,
            payload={"task_id": task_id},
        )
        return session

    def _pause(self, session: StudySession) -> None:
        interval = (
            self.db.query(StudySessionInterval)
            .filter_by(study_session_id=session.id, ended_at=None)
            .one_or_none()
        )
        if interval is not None:
            interval.ended_at = now()
            interval.end_reason = "paused"
        session.status = "paused"
        session.pause_count += 1
        session.version += 1

    def _view(self, cue: StartCueRecord | None) -> dict:
        if cue is None or cue.status in {"expired", "accepted", "superseded"}:
            return {"status": "none"}
        if cue.status != "presented":
            return {"status": cue.status, "id": cue.id, "version": cue.version}
        tasks = []
        for task_id in cue.earlier_task_ids or []:
            task = self.db.get(Task, task_id)
            if task is not None:
                tasks.append({"id": task.id, "title": task.title, "due": False})
        due = self.db.get(Task, cue.due_task_id)
        if due is not None:
            tasks.append({"id": due.id, "title": due.title, "due": True})
        actions = []
        for index, command in enumerate(cue.actions or []):
            actions.append({
                "command": command,
                "label": self._label(command, cue),
                "primary": index == 0 and command != "snooze_once",
                "quiet": command == "snooze_once",
            })
        return {
            "status": "presented",
            "id": cue.id,
            "version": cue.version,
            "text": cue.text,
            "tasks": tasks,
            "actions": actions,
        }

    def _label(self, command: str, cue: StartCueRecord) -> str:
        due = self.db.get(Task, cue.due_task_id)
        due_title = due.title if due else "这项"
        current = "当前这项"
        if cue.current_session_id:
            session = self.db.get(StudySession, cue.current_session_id)
            if session is not None and session.task_id:
                task = self.db.get(Task, session.task_id)
                if task is not None:
                    current = task.title
        if command == "start_due_task":
            return f"开始{due_title}"
        if command == "continue_current":
            return f"继续{current}"
        if command == "pause_current_and_start_due":
            return f"暂停{current}，开始{due_title}"
        return "等一下"
