from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..memory import record_learning_event
from ..models import DailySchedule, PlanDraft, Task, now

MAX_DAILY_MINUTES = 480


class PlanningDomainService:
    def __init__(self, db: Session):
        self.db = db

    def save_draft(
        self,
        ward_id: str,
        plan_date: date,
        items: list[dict],
        pending_fields: list[str] | None = None,
    ) -> PlanDraft:
        if (
            sum(int(item.get("planned_minutes", 0)) for item in items)
            > MAX_DAILY_MINUTES
        ):
            raise HTTPException(400, "计划总时长超过当天上限")
        known = {
            task.id for task in self.db.query(Task).filter_by(ward_id=ward_id).all()
        }
        for item in items:
            existing, new = item.get("assignment_id"), bool(item.get("new_task"))
            if new == bool(existing) or (existing and existing not in known):
                raise HTTPException(400, "计划草稿包含无效任务来源")
            if (
                not str(item.get("title", "")).strip()
                or not 1 <= int(item.get("planned_minutes", 0)) <= MAX_DAILY_MINUTES
            ):
                raise HTTPException(400, "计划草稿任务不完整")
        schedule = (
            self.db.query(DailySchedule)
            .filter_by(ward_id=ward_id, schedule_date=plan_date)
            .one_or_none()
        )
        draft = (
            self.db.query(PlanDraft)
            .filter_by(ward_id=ward_id, plan_date=plan_date)
            .one_or_none()
        )
        if draft is None:
            draft = PlanDraft(
                ward_id=ward_id,
                plan_date=plan_date,
                base_schedule_version=schedule.version if schedule else 0,
            )
            self.db.add(draft)
        draft.items, draft.pending_fields, draft.status = (
            items,
            pending_fields or [],
            "active",
        )
        draft.version = (draft.version or 0) + 1
        self.db.flush()
        return draft

    def confirm(self, ward_id: str, draft_id: str) -> DailySchedule:
        draft = self.db.get(PlanDraft, draft_id)
        if draft is None or draft.ward_id != ward_id:
            raise HTTPException(404, "计划草稿不存在")
        if draft.status == "confirmed":
            schedule = (
                self.db.query(DailySchedule)
                .filter_by(ward_id=ward_id, schedule_date=draft.plan_date)
                .one_or_none()
            )
            if schedule is not None:
                return schedule
        if draft.status != "active":
            raise HTTPException(409, "计划草稿当前不可确认")
        if draft.pending_fields:
            raise HTTPException(409, "计划草稿仍有待确认信息")
        schedule = (
            self.db.query(DailySchedule)
            .filter_by(ward_id=ward_id, schedule_date=draft.plan_date)
            .one_or_none()
        )
        if (schedule.version if schedule else 0) != draft.base_schedule_version:
            raise HTTPException(409, "计划已变化，请重新审阅")
        if schedule is None:
            schedule = DailySchedule(ward_id=ward_id, schedule_date=draft.plan_date)
            self.db.add(schedule)
            self.db.flush()
        existing = self.db.query(Task).filter_by(schedule_id=schedule.id).all()
        if any(task.status not in {"open", "pending"} for task in existing):
            raise HTTPException(409, "已开始的计划不能修改")
        for task in existing:
            task.schedule_id = task.position = task.planned_minutes = None
        for position, item in enumerate(draft.items):
            task = (
                self.db.get(Task, item["assignment_id"])
                if item.get("assignment_id")
                else Task(
                    ward_id=ward_id,
                    title=item["title"],
                    details=item.get("details"),
                    source="ward",
                )
            )
            if task is not None and task.ward_id != ward_id:
                raise HTTPException(403, "计划草稿引用了其他 Ward 的任务")
            if task is not None and task.schedule_id is not None and task.status not in {"open", "pending"}:
                raise HTTPException(409, "已开始的任务不能重新安排")
            if task.id is None:
                self.db.add(task)
                self.db.flush()
            task.schedule_id, task.position, task.planned_minutes = (
                schedule.id,
                position,
                int(item["planned_minutes"]),
            )
        schedule.status, schedule.confirmed_at, schedule.version = (
            "confirmed",
            now(),
            schedule.version + 1,
        )
        draft.status = "confirmed"
        self.db.flush()
        record_learning_event(
            self.db,
            ward_id=ward_id,
            event_type="planning.confirmed",
            source_type="plan_draft",
            source_id=draft.id,
            source_version=draft.version,
            payload={"schedule_id": schedule.id, "task_count": len(draft.items)},
        )
        return schedule
