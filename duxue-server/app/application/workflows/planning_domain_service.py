from __future__ import annotations

from datetime import date, datetime, timedelta
import re
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.persistence.models import DailySchedule, PlanDraft, Task, now

MAX_DAILY_MINUTES = 480


class PlanningDomainService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _slot(item: dict) -> tuple[datetime, datetime] | None:
        start_at = item.get("start_at")
        if not start_at:
            return None
        try:
            start = datetime.fromisoformat(start_at)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "计划开始时间格式无效") from error
        minutes = item.get("planned_minutes")
        if minutes is None:
            return None
        end = start + timedelta(minutes=int(minutes))
        if item.get("end_at") and datetime.fromisoformat(item["end_at"]) != end:
            raise HTTPException(400, "计划结束时间必须由开始时间和预计时长计算")
        item["end_at"] = end.isoformat()
        return start, end

    def _resolve_timeline(self, items: list[dict], pending: set[str]) -> None:
        """Derive relative slots and reject an unbound time copied to tasks."""
        by_id = {item["assignment_id"]: item for item in items if item.get("assignment_id")}
        starts: dict[str, list[dict]] = {}
        for item in items:
            if item.get("start_at"):
                starts.setdefault(item["start_at"], []).append(item)
        # A single Ward time cannot silently become the start of multiple tasks.
        for duplicated in starts.values():
            if len(duplicated) > 1:
                for item in duplicated:
                    item.pop("start_at", None)
                    item.pop("end_at", None)
                pending.add("ambiguous_target_task")

        # Resolve chained before/after expressions only from an already-known
        # slot; a cycle or missing reference remains a clarification.
        for _ in range(len(items)):
            changed = False
            for item in items:
                if item.get("start_at"):
                    continue
                after = by_id.get(item.get("after_assignment_id"))
                before = by_id.get(item.get("before_assignment_id"))
                if after and self._slot(after):
                    item["start_at"] = after["end_at"]
                    item["slot_source"] = "deterministic_derived"
                    changed = True
                elif before and self._slot(before) and item.get("planned_minutes") is not None:
                    start = datetime.fromisoformat(before["start_at"]) - timedelta(minutes=int(item["planned_minutes"]))
                    item["start_at"] = start.isoformat()
                    item["slot_source"] = "deterministic_derived"
                    changed = True
            if not changed:
                break
        for item in items:
            reference = item.get("after_assignment_id") or item.get("before_assignment_id")
            if reference and (reference == item.get("assignment_id") or reference not in by_id):
                pending.add("ambiguous_target_task")
            if reference and not item.get("start_at"):
                pending.add("ambiguous_target_task")

    @staticmethod
    def _normalised_task_name(value: object) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKC", str(value)).casefold()
            if not char.isspace() and char not in "-_·,，。！？!?（）()"
        )

    def resolve_task_references(
        self, ward_id: str, items: list[dict], *, trust_explicit_ids: bool = False,
    ) -> tuple[list[dict], set[str]]:
        """Bind human task references before any candidate can register a Task.

        An intake model may describe a task but must never select its database
        ID.  A direct legacy adapter may pass an already-authorized ID.
        """
        tasks = [task for task in self.db.query(Task).filter_by(ward_id=ward_id).all()
                 if task.status not in {"completed", "cancelled"} and task.schedule_id is None]
        resolved: list[dict] = []
        pending: set[str] = set()
        for raw in items:
            item = dict(raw)
            explicit_id = item.get("assignment_id") if trust_explicit_ids else None
            if explicit_id:
                task = next((candidate for candidate in tasks if candidate.id == explicit_id), None)
                if task is None:
                    raise HTTPException(400, "计划草稿包含无效任务来源")
                candidates = [task]
            else:
                # Model-provided IDs are discarded.  Evaluate both the model's
                # human reference and title: the latter often preserves the
                # exact pool label even when the former paraphrases it.
                item.pop("assignment_id", None)
                references = []
                for value in (item.get("task_reference"), item.get("title")):
                    reference = self._normalised_task_name(value)
                    if reference and reference not in references:
                        references.append(reference)
                candidate_by_id: dict[str, Task] = {}
                for reference in references:
                    exact = [task for task in tasks if self._normalised_task_name(task.title) == reference]
                    prefix = [task for task in tasks if reference and
                              (self._normalised_task_name(task.title).startswith(reference) or
                               reference.startswith(self._normalised_task_name(task.title)))]
                    for task in exact or prefix:
                        candidate_by_id[task.id] = task
                candidates = list(candidate_by_id.values())
            if len(candidates) == 1:
                task = candidates[0]
                item.update({"assignment_id": task.id, "new_task": False,
                             "title": task.title, "details": task.details,
                             "planned_minutes": item.get("planned_minutes") or task.planned_minutes})
                resolved.append(item)
                continue
            if len(candidates) > 1:
                # Never turn an ambiguous existing reference into a same-name
                # task candidate.  The pool remains visible for a later choice.
                pending.add("ambiguous_target_task")
                continue
            item["new_task"] = True
            resolved.append(item)
        for item in resolved:
            for field, output in (("after_task_reference", "after_assignment_id"),
                                  ("before_task_reference", "before_assignment_id")):
                reference = item.get(field)
                if not reference or item.get(output):
                    continue
                name = self._normalised_task_name(reference)
                candidates = [task for task in tasks if name and
                              (self._normalised_task_name(task.title) == name or
                               self._normalised_task_name(task.title).startswith(name))]
                if len(candidates) == 1:
                    item[output] = candidates[0].id
                else:
                    pending.add("ambiguous_target_task")
        return resolved, pending

    def register_tasks(self, ward_id: str, items: list[dict]) -> list[dict]:
        """Turn validated new-task candidates into task-pool records before review."""
        result: list[dict] = []
        for item in items:
            copied = dict(item)
            if copied.get("new_task") and copied.get("assignment_id"):
                raise HTTPException(400, "计划草稿包含无效任务来源")
            if not copied.get("new_task"):
                result.append(copied)
                continue
            title = str(copied.get("title", "")).strip()
            minutes = copied.get("planned_minutes")
            if not title:
                raise HTTPException(400, "计划草稿任务不完整")
            if minutes is None:
                # A missing duration is a clarification state, not a phantom
                # PlanDraft item.  It becomes a Task only after Ward supplies it.
                continue
            if not 1 <= int(minutes) <= MAX_DAILY_MINUTES:
                raise HTTPException(400, "计划草稿任务不完整")
            # Coordinator command idempotency protects retries.  This extra
            # same-turn match prevents a model candidate from duplicating one title.
            task = self.db.query(Task).filter_by(
                ward_id=ward_id, title=title, schedule_id=None, status="open",
            ).first()
            if task is None:
                task = Task(ward_id=ward_id, title=title, details=copied.get("details"),
                            planned_minutes=int(minutes), source="ward")
                self.db.add(task)
                self.db.flush()
            copied.update({"assignment_id": task.id, "new_task": False,
                           "planned_minutes": task.planned_minutes})
            result.append(copied)
        return result

    def _draft_items_for_pool(self, ward_id: str, items: list[dict]) -> list[dict]:
        known = {task.id: task for task in self.db.query(Task).filter_by(ward_id=ward_id).all()}
        by_id = {item.get("assignment_id"): dict(item) for item in items if item.get("assignment_id")}
        # A review always makes the unfinished pool visible.  Existing scheduled
        # tasks are intentionally excluded: re-planning them is a separate flow.
        for task in known.values():
            if task.status in {"completed", "cancelled"} or task.schedule_id is not None:
                continue
            by_id.setdefault(task.id, {
                "assignment_id": task.id, "new_task": False, "title": task.title,
                "details": task.details, "planned_minutes": task.planned_minutes,
            })
        return list(by_id.values())

    @staticmethod
    def _duration_minutes(value: object) -> int | None:
        matched = re.search(r"(\d{1,3}|[一二三四五六七八九十两]{1,3})\s*分(?:钟)?", str(value).strip())
        if not matched:
            return None
        raw = matched.group(1)
        if raw.isdigit():
            minutes = int(raw)
        else:
            digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9}
            if raw == "十":
                minutes = 10
            elif raw.startswith("十"):
                minutes = 10 + digits.get(raw[1:], 0)
            elif raw.endswith("十"):
                minutes = digits.get(raw[0], 0) * 10
            elif "十" in raw:
                tens, ones = raw.split("十", 1)
                minutes = digits.get(tens, 0) * 10 + digits.get(ones, 0)
            else:
                minutes = digits.get(raw, 0)
        return minutes if 1 <= minutes <= MAX_DAILY_MINUTES else None

    def _duration_batch(self, ward_id: str, original_items: list[dict]) -> dict | None:
        """Keep targets stable before incomplete new-task candidates are omitted."""
        known = {task.id: task for task in self.db.query(Task).filter_by(ward_id=ward_id).all()}
        slots: list[dict] = []
        for item in original_items:
            if item.get("planned_minutes") is not None:
                continue
            title, task_id = str(item.get("title") or "").strip(), item.get("assignment_id")
            if task_id and task_id in known:
                target = {"kind": "existing_task", "task_id": task_id}
                title = title or known[task_id].title
            elif item.get("new_task") and title:
                target = {"kind": "new_task_candidate", "candidate_id": str(uuid4()),
                          "title": title, "details": item.get("details")}
            else:
                continue
            slots.append({"slot_id": str(uuid4()), "field": "planned_minutes", "title": title,
                          "target": target})
        return {"batch_id": str(uuid4()), "issued_draft_version": None, "slots": slots} if slots else None

    @staticmethod
    def _clarification_batch(draft: PlanDraft) -> dict | None:
        batch = (draft.working_state or {}).get("active_clarification_batch")
        return batch if isinstance(batch, dict) and batch.get("slots") else None

    def resolve_duration_clarification(
        self, *, ward_id: str, plan_date: date, answers: list[dict] | None = None,
    ) -> tuple[PlanDraft, int] | None:
        """Apply already-structured slot updates; never interpret Ward text."""
        draft = self.db.query(PlanDraft).filter_by(ward_id=ward_id, plan_date=plan_date, status="active").one_or_none()
        if draft is None:
            return None
        batch = self._clarification_batch(draft)
        if batch is None or batch.get("issued_draft_version") != draft.version:
            return None
        slots, resolved = list(batch["slots"]), {}
        for answer in answers or []:
            minutes = self._duration_minutes(answer.get("value", ""))
            if minutes and any(slot["slot_id"] == answer.get("slot_id") for slot in slots):
                resolved[answer["slot_id"]] = minutes
        if not resolved:
            return draft, 0
        items = [dict(item) for item in draft.items]
        for slot in slots:
            minutes = resolved.get(slot["slot_id"])
            if minutes is None:
                continue
            target = slot["target"]
            if target["kind"] == "existing_task":
                task = self.db.get(Task, target["task_id"])
                if task is None or task.ward_id != ward_id:
                    continue
                task.planned_minutes = minutes
                item = next((item for item in items if item.get("assignment_id") == task.id), None)
                if item is None:
                    items.append({"assignment_id": task.id, "new_task": False, "title": task.title,
                                  "details": task.details, "planned_minutes": minutes})
                else:
                    item["planned_minutes"] = minutes
            else:
                task = Task(ward_id=ward_id, title=target["title"], details=target.get("details"),
                            planned_minutes=minutes, source="ward")
                self.db.add(task)
                self.db.flush()
                items.append({"assignment_id": task.id, "new_task": False, "title": task.title,
                              "details": task.details, "planned_minutes": minutes})
        remaining = [slot for slot in slots if slot["slot_id"] not in resolved]
        state = dict(draft.working_state or {})
        if remaining:
            batch["slots"] = remaining
            state["active_clarification_batch"] = batch
        else:
            state.pop("active_clarification_batch", None)
        pending = set(draft.pending_fields)
        if remaining:
            pending.add("planned_minutes")
        else:
            pending.discard("planned_minutes")
        draft.items = self._draft_items_for_pool(ward_id, items)
        draft.pending_fields, draft.working_state = sorted(pending), state
        draft.version += 1
        self.db.flush()
        return draft, len(resolved)

    def plan_draft_view(self, ward_id: str, draft_id: str) -> dict:
        draft = self.db.get(PlanDraft, draft_id)
        if draft is None or draft.ward_id != ward_id:
            raise HTTPException(404, "计划草稿不存在")
        items = [dict(item) for item in draft.items]
        slots: list[tuple[dict, datetime, datetime]] = []
        for item in items:
            slot = self._slot(item)
            if slot:
                slots.append((item, *slot))
        conflicts: set[str] = set()
        for index, (item, start, end) in enumerate(slots):
            for other, other_start, other_end in slots[index + 1:]:
                if start < other_end and other_start < end:
                    conflicts.update({item["assignment_id"], other["assignment_id"]})
        valid_slots = 0
        for item in items:
            item["schedule_conflict"] = item.get("assignment_id") in conflicts
            item["will_enter_plan"] = (
                self._slot(item) is not None and not item["schedule_conflict"] and not draft.pending_fields
            )
            valid_slots += int(item["will_enter_plan"])
        return {"draft_id": draft.id, "object_version": draft.version,
                "plan_date": draft.plan_date.isoformat(), "items": items,
                "confirm_enabled": bool(valid_slots and not draft.pending_fields and not conflicts),
                "pending_fields": draft.pending_fields,
                "clarification_batch": self._clarification_batch(draft)}

    def save_draft(
        self,
        ward_id: str,
        plan_date: date,
        items: list[dict],
        pending_fields: list[str] | None = None,
    ) -> PlanDraft:
        pending = set(pending_fields or [])
        original_items = [dict(item) for item in items]
        if (
            sum(int(item["planned_minutes"]) for item in items if item.get("planned_minutes") is not None)
            > MAX_DAILY_MINUTES
        ):
            raise HTTPException(400, "计划总时长超过当天上限")
        items = self.register_tasks(ward_id, items)
        known = {task.id for task in self.db.query(Task).filter_by(ward_id=ward_id).all()}
        for item in items:
            existing, new = item.get("assignment_id"), bool(item.get("new_task"))
            if new or not existing or existing not in known:
                raise HTTPException(400, "计划草稿包含无效任务来源")
            minutes = item.get("planned_minutes")
            if not str(item.get("title", "")).strip():
                raise HTTPException(400, "计划草稿任务不完整")
            if minutes is None:
                if "planned_minutes" not in pending:
                    raise HTTPException(400, "请补充任务预计时长")
                continue
            if not 1 <= int(minutes) <= MAX_DAILY_MINUTES:
                raise HTTPException(400, "计划草稿任务不完整")
            if item.get("start_at"):
                item["slot_source"] = "ward_explicit"
        self._resolve_timeline(items, pending)
        for item in items:
            self._slot(item)
        items = self._draft_items_for_pool(ward_id, items)
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
                version=0,
            )
            self.db.add(draft)
        # A later turn may carry a scheduling intent while duration slots are
        # still open.  Preserve those issued targets rather than replacing them
        # with whatever the scheduling parser happened to repeat.
        existing_batch = self._clarification_batch(draft)
        batch = self._duration_batch(ward_id, original_items) if "planned_minutes" in pending else None
        if existing_batch and "planned_minutes" in pending:
            batch = existing_batch
        if batch:
            batch["issued_draft_version"] = (draft.version or 0) + 1
        normalized_items = [dict(item) for item in items]
        normalized_pending = sorted(pending)
        state = {"active_clarification_batch": batch} if batch else {}
        changed = (draft.items != normalized_items or draft.pending_fields != normalized_pending
                   or draft.working_state != state or draft.status != "active")
        draft.items, draft.pending_fields, draft.working_state, draft.status = normalized_items, normalized_pending, state, "active"
        if changed:
            draft.version = (draft.version or 0) + 1
        self.db.flush()
        return draft

    def confirm(self, ward_id: str, draft_id: str, expected_draft_version: int | None = None) -> DailySchedule:
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
        if expected_draft_version is not None and draft.version != expected_draft_version:
            raise HTTPException(409, "计划草稿已变化，请重新审阅")
        if draft.pending_fields:
            raise HTTPException(409, "计划草稿仍有待确认信息")
        schedule = (
            self.db.query(DailySchedule)
            .filter_by(ward_id=ward_id, schedule_date=draft.plan_date)
            .one_or_none()
        )
        if (schedule.version if schedule else 0) != draft.base_schedule_version:
            raise HTTPException(409, "计划已变化，请重新审阅")
        selected = []
        for item in draft.items:
            copied = dict(item)
            if self._slot(copied) is not None:
                selected.append(copied)
        if not selected:
            raise HTTPException(409, "计划草稿没有可确认的时间槽")
        selected.sort(key=lambda item: item["start_at"])
        for previous, current in zip(selected, selected[1:]):
            if previous["end_at"] > current["start_at"]:
                raise HTTPException(409, "计划存在时间冲突")
        if sum(int(item["planned_minutes"]) for item in selected) > MAX_DAILY_MINUTES:
            raise HTTPException(409, "计划总时长超过当天上限")
        if schedule is None:
            schedule = DailySchedule(ward_id=ward_id, schedule_date=draft.plan_date)
            self.db.add(schedule)
            self.db.flush()
        existing = self.db.query(Task).filter_by(schedule_id=schedule.id).all()
        if any(task.status not in {"open", "pending"} for task in existing):
            raise HTTPException(409, "已开始的计划不能修改")
        for task in existing:
            # planned_minutes belongs to Task (the pool estimate), not this
            # schedule membership.  Removing a schedule must not erase it.
            task.schedule_id = task.position = None
        for position, item in enumerate(selected):
            task = self.db.get(Task, item["assignment_id"])
            if task is not None and task.ward_id != ward_id:
                raise HTTPException(403, "计划草稿引用了其他 Ward 的任务")
            if task is not None and task.schedule_id is not None and task.status not in {"open", "pending"}:
                raise HTTPException(409, "已开始的任务不能重新安排")
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
        publish_learning_fact(
            self.db,
            ward_id=ward_id,
            event_type="planning.confirmed",
            source_type="plan_draft",
            source_id=draft.id,
            source_version=draft.version,
            payload={"schedule_id": schedule.id, "task_count": len(selected)},
        )
        return schedule
