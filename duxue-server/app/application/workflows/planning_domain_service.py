from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.contexts.planning.domain.scheduling import (
    SchedulingService,
    TaskReferenceResolver,
)
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.persistence.models import (
    DailySchedule,
    OutboxEvent,
    PlanDraft,
    StudySession,
    Task,
    Ward,
    now,
)

from .planning_operations import PlanningOperations

MAX_DAILY_MINUTES = 480


class PlanningDomainService(PlanningOperations):
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
        for item in items:
            if item.get("slot_source") == "deterministic_derived":
                item.pop("start_at", None)
                item.pop("end_at", None)
        by_id = {item["assignment_id"]: item for item in items if item.get("assignment_id")}
        starts: dict[str, list[dict]] = {}
        for item in items:
            if item.get("start_at"):
                starts.setdefault(item["start_at"], []).append(item)
        # A single Ward time cannot silently become the start of multiple tasks.
        for duplicated in starts.values():
            if len(duplicated) > 1 and not all(i.get("target_bound") for i in duplicated):
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
            candidates = [{"id": task.id, "title": task.title}
                          for task in self.db.query(Task).filter_by(ward_id=ward_id).all()
                          if task.status not in {"completed", "cancelled"}]
            conflicts = TaskReferenceResolver.title_conflicts(title, candidates)
            if conflicts:
                raise HTTPException(409, {
                    "code": "duplicate_task_title",
                    "message": "任务标题与已有任务重复，请明确选择已有任务或新增同名任务",
                    "candidates": conflicts,
                })
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
        matched = re.fullmatch(r"(\d{1,3}|[一二三四五六七八九十两]{1,3})\s*分(?:钟)?", str(value).strip())
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
        """Compatibility name for the generalized, issued-slot answer use case."""
        draft = self.active_draft(ward_id, plan_date)
        if draft is None or self._clarification_batch(draft) is None:
            return None
        if not answers:
            return draft, 0
        updated = self.apply_operations(ward_id, plan_date, [], answers=answers, command_id=str(uuid4()))
        return updated, len(answers)

    def _lock_ward(self, ward_id):
        # Serializes first-schedule creation as well as concurrent draft writes.
        if self.db.query(Ward).filter_by(id=ward_id).with_for_update().first() is None:
            raise HTTPException(404, "学生不存在")

    def active_draft(self, ward_id, plan_date):
        return self.db.query(PlanDraft).filter_by(
            ward_id=ward_id, plan_date=plan_date, status="active").one_or_none()

    def _schedule(self, ward_id, plan_date):
        return self.db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).populate_existing().one_or_none()

    def _check_not_started(self, schedule):
        if not schedule:
            return
        tasks = self.db.query(Task).filter_by(schedule_id=schedule.id).all()
        ids = [t.id for t in tasks]
        if (any(t.status not in {"open", "pending"} for t in tasks)
                or (ids and self.db.query(StudySession).filter(StudySession.task_id.in_(ids)).first())):
            raise HTTPException(409, "已开始的计划不能修改")

    def delete_task(self, ward_id: str, task_id: str) -> Task:
        self._lock_ward(ward_id)
        task = self.db.get(Task, task_id)
        if task is None or task.ward_id != ward_id:
            raise HTTPException(404, "任务不存在")
        if task.status not in {"open", "pending"}:
            raise HTTPException(409, "任务当前不可删除")
        if self.db.query(StudySession).filter_by(task_id=task.id).first():
            raise HTTPException(409, "已有学习记录的任务不能删除")
        if task.schedule_id:
            raise HTTPException(409, "已进入计划的任务需要确认后删除")
        for schedule in self.db.query(DailySchedule).filter_by(ward_id=ward_id).all():
            items = [item for item in (schedule.items or []) if item.get("assignment_id") != task.id]
            if len(items) != len(schedule.items or []):
                schedule.items = items
                schedule.version += 1
        for draft in self.db.query(PlanDraft).filter_by(ward_id=ward_id).all():
            items = [item for item in (draft.items or []) if item.get("assignment_id") != task.id]
            if len(items) != len(draft.items or []):
                state = deepcopy(draft.working_state or {})
                state["task_versions"] = {
                    ident: version for ident, version in state.get("task_versions", {}).items()
                    if ident != task.id}
                state["proposed_task_changes"] = {
                    ident: value for ident, value in state.get("proposed_task_changes", {}).items()
                    if ident != task.id}
                draft.items = items
                draft.working_state = state
                draft.version += 1
        self.db.delete(task)
        self.db.flush()
        return task

    def _ensure_draft(self, ward_id, plan_date):
        self._lock_ward(ward_id)
        draft = self.active_draft(ward_id, plan_date)
        if draft:
            return draft
        schedule = self._schedule(ward_id, plan_date)
        self._check_not_started(schedule)
        items = deepcopy(schedule.items or []) if schedule else []
        # Fail closed for pre-migration schedules that have no timing evidence.
        scheduled = self.db.query(Task).filter_by(schedule_id=schedule.id).all() if schedule else []
        known = {i.get("assignment_id") for i in items}
        for task in scheduled:
            if task.id not in known:
                items.append({"assignment_id": task.id, "title": task.title,
                              "planned_minutes": task.planned_minutes, "new_task": False,
                              "schedule_requested": True})
        draft = PlanDraft(ward_id=ward_id, plan_date=plan_date, status="active", version=0,
                          base_schedule_version=schedule.version if schedule else 0,
                          items=items, pending_fields=[], working_state={})
        self.db.add(draft)
        self.db.flush()
        return draft

    def _persist_review(self, draft, items, pending, state):
        for item in items:
            item.pop("end_at", None)
        self._resolve_timeline(items, pending)
        for item in items:
            if not item.get("deferred"):
                self._slot(item)
        versions = dict(state.get("task_versions", {}))
        for item in items:
            task = self.db.get(Task, item["assignment_id"])
            if task and item["assignment_id"] not in versions:
                versions[task.id] = task.version
        state["task_versions"] = versions
        batch = state.get("active_clarification_batch")
        draft.version += 1
        if batch:
            batch["issued_draft_version"] = draft.version
        draft.items, draft.pending_fields, draft.working_state = items, sorted(pending), state
        self.db.flush()
        return draft

    def save_draft(self, ward_id: str, plan_date: date, items: list[dict],
                   pending_fields: list[str] | None = None) -> PlanDraft:
        # Compatibility entry: trusted structured items still pass all rules.
        self._lock_ward(ward_id)
        pending = set(pending_fields or [])
        original_items = deepcopy(items)
        if sum(int(i["planned_minutes"]) for i in items if i.get("planned_minutes") is not None) > MAX_DAILY_MINUTES:
            raise HTTPException(400, "计划总时长超过当天上限")
        items = self.register_tasks(ward_id, items)
        known_titles = [{"id": task.id, "title": task.title}
                        for task in self.db.query(Task).filter_by(ward_id=ward_id).all()
                        if task.status not in {"completed", "cancelled"}]
        requested_titles: dict[str, str] = {}
        for item in items:
            task = self.db.get(Task, item.get("assignment_id"))
            if task is None or task.ward_id != ward_id or item.get("new_task"):
                raise HTTPException(400, "计划草稿包含无效任务来源")
            if task.status not in {"open", "pending"}:
                raise HTTPException(409, "任务当前不可修改")
            if not str(item.get("title") or "").strip():
                raise HTTPException(400, "计划草稿任务不完整")
            title = str(item["title"]).strip()
            conflicts = TaskReferenceResolver.title_conflicts(title, known_titles, exclude_ids=[task.id])
            conflicts.extend({"id": other_id, "title": other_title}
                             for other_id, other_title in requested_titles.items()
                             if TaskReferenceResolver.normalise(other_title)
                             == TaskReferenceResolver.normalise(title)
                             and other_id != task.id)
            if conflicts:
                raise HTTPException(409, {
                    "code": "duplicate_task_title",
                    "message": "任务标题与已有任务重复，请明确选择已有任务或新增同名任务",
                    "candidates": conflicts,
                })
            requested_titles[task.id] = title
            minutes = item.get("planned_minutes")
            if minutes is None and "planned_minutes" not in pending:
                raise HTTPException(400, "请补充任务预计时长")
            if minutes is not None and not 1 <= int(minutes) <= MAX_DAILY_MINUTES:
                raise HTTPException(400, "计划草稿任务不完整")
        draft = self._ensure_draft(ward_id, plan_date)
        state = deepcopy(draft.working_state or {})
        merged = {i["assignment_id"]: dict(i) for i in draft.items}
        for patch in items:
            task = self.db.get(Task, patch["assignment_id"])
            current = merged.setdefault(task.id, {})
            clean = {k: v for k, v in patch.items() if v is not None}
            if patch.get("start_at") and patch.get("slot_source") != "deterministic_derived":
                clean["slot_source"] = "ward_explicit"
                current.pop("after_assignment_id", None)
                current.pop("before_assignment_id", None)
            current.update(clean)
            if not task.schedule_id and patch.get("planned_minutes") is not None:
                task.planned_minutes = int(patch["planned_minutes"])
                self.db.flush()
                state.setdefault("task_versions", {})[task.id] = task.version
            elif task.schedule_id:
                state.setdefault("proposed_task_changes", {})[task.id] = {
                    "title": current["title"], "planned_minutes": current.get("planned_minutes")}
        normalized = self._draft_items_for_pool(ward_id, list(merged.values()))
        existing_batch = self._clarification_batch(draft)
        batch = self._duration_batch(ward_id, original_items) if "planned_minutes" in pending else None
        if existing_batch:
            batch = deepcopy(existing_batch)
            pending.update(slot["field"] for slot in batch["slots"])
        if batch:
            state["active_clarification_batch"] = batch
        return self._persist_review(draft, normalized, pending, state)

    def plan_draft_view(self, ward_id: str, draft_id: str) -> dict:
        draft = self.db.get(PlanDraft, draft_id)
        if draft is None or draft.ward_id != ward_id:
            raise HTTPException(404, "计划草稿不存在")
        items = deepcopy(draft.items)
        for item in items:
            if not item.get("deferred"):
                self._slot(item)
        conflicts = SchedulingService.validate_schedule(items)
        conflict_ids = {ident for c in conflicts for ident in c["task_ids"]}
        state = draft.working_state or {}
        pending = set(draft.pending_fields)
        batch = self._clarification_batch(draft)
        if batch:
            pending.update(slot["field"] for slot in batch["slots"])
        for item in items:
            task = self.db.get(Task, item["assignment_id"])
            if task and task.source == "guardian" and not item.get("start_at") and not item.get("unscheduled_reason") and not pending:
                pending.add("unscheduled_reason")
            if item.get("schedule_requested") and not item.get("deferred") and not item.get("start_at"):
                pending.add("start_at")
            item["schedule_conflict"] = item["assignment_id"] in conflict_ids
            item["will_enter_plan"] = bool(item.get("start_at") and item.get("end_at")
                                           and not item.get("deferred") and not item["schedule_conflict"])
        schedule = self._schedule(ward_id, draft.plan_date)
        stale = (schedule.version if schedule else 0) != draft.base_schedule_version
        for task_id, version in state.get("task_versions", {}).items():
            task = self.db.get(Task, task_id)
            stale |= task is None or task.version != version
        proposed_task_deletions = state.get("proposed_task_deletions", {})
        for task_id, payload in proposed_task_deletions.items():
            task = self.db.get(Task, task_id)
            stale |= task is None or task.version != payload.get("task_version")
        if stale:
            pending.add("version_conflict")
        return {"draft_id": draft.id, "object_version": draft.version,
                "plan_date": draft.plan_date.isoformat(), "items": items,
                "confirm_enabled": bool(draft.status == "active" and not pending and not conflicts
                                        and (any(i["will_enter_plan"] for i in items) or proposed_task_deletions)),
                "pending_fields": sorted(pending), "conflicts": conflicts,
                "clarification_batch": batch,
                "operation_results": state.get("operation_results", []),
                "planning_agent_loop": state.get("planning_agent_loop", {}),
                "is_revision": bool(schedule), "proposed_task_changes": state.get("proposed_task_changes", {}),
                "proposed_task_deletions": proposed_task_deletions}

    def confirm(self, ward_id: str, draft_id: str, expected_draft_version: int | None = None) -> DailySchedule:
        self._lock_ward(ward_id)
        draft = self.db.query(PlanDraft).filter_by(id=draft_id, ward_id=ward_id).with_for_update().populate_existing().one_or_none()
        if draft is None:
            raise HTTPException(404, "计划草稿不存在")
        schedule = self._schedule(ward_id, draft.plan_date)
        if draft.status == "confirmed" and schedule:
            return schedule
        if draft.status != "active" or (expected_draft_version is not None and draft.version != expected_draft_version):
            raise HTTPException(409, "计划草稿已变化，请重新审阅")
        if (schedule.version if schedule else 0) != draft.base_schedule_version:
            raise HTTPException(409, "计划已变化，请重新审阅")
        self._check_not_started(schedule)
        tasks = {t.id: t for t in self.db.query(Task).filter_by(ward_id=ward_id).with_for_update().populate_existing().all()}
        self._check_not_started(schedule)
        state = deepcopy(draft.working_state or {})
        for ident, version in state.get("task_versions", {}).items():
            if ident not in tasks or tasks[ident].version != version:
                raise HTTPException(409, "任务已变化，请重新审阅")
        proposed_deletions = state.get("proposed_task_deletions", {})
        for ident, payload in proposed_deletions.items():
            if ident not in tasks or tasks[ident].version != payload.get("task_version"):
                raise HTTPException(409, "任务已变化，请重新审阅")
        view = self.plan_draft_view(ward_id, draft.id)
        if not view["confirm_enabled"]:
            raise HTTPException(409, {"code": "plan_not_confirmable", "message": "计划草稿仍有待确认信息或时间冲突",
                                      "draft": view})
        selected = sorted((i for i in draft.items if i.get("start_at") and not i.get("deferred")),
                          key=lambda i: SchedulingService.instant(i["start_at"]))
        for item in selected:
            task = tasks.get(item["assignment_id"])
            if task is None or task.status not in {"open", "pending"}:
                raise HTTPException(409, "任务当前不可安排")
            if task.schedule_id and (schedule is None or task.schedule_id != schedule.id):
                raise HTTPException(409, "任务已在其他计划中")
        if schedule is None:
            schedule = DailySchedule(ward_id=ward_id, schedule_date=draft.plan_date, version=0, items=[], history=[])
            self.db.add(schedule)
            self.db.flush()
        history = list(schedule.history or [])
        if schedule.status == "confirmed":
            history.append({"version": schedule.version, "items": deepcopy(schedule.items),
                            "confirmed_at": schedule.confirmed_at.isoformat() if schedule.confirmed_at else None,
                            "actor_id": ward_id})
        selected_ids = {i["assignment_id"] for i in selected}
        deletion_ids = set(proposed_deletions)
        for task in tasks.values():
            if task.schedule_id == schedule.id and task.id not in selected_ids:
                task.schedule_id = task.position = None
        for task_id in deletion_ids:
            task = tasks.get(task_id)
            if task is not None:
                self.db.delete(task)
        for position, item in enumerate(selected):
            task = tasks[item["assignment_id"]]
            task.title, task.planned_minutes = item["title"], int(item["planned_minutes"])
            task.schedule_id, task.position = schedule.id, position
        schedule.items, schedule.history = deepcopy(selected), history
        schedule.status, schedule.confirmed_at = "confirmed", now()
        schedule.version += 1
        state["confirmed_schedule_version"] = schedule.version
        draft.working_state, draft.status = state, "confirmed"
        draft.version += 1
        self.db.flush()
        publish_learning_fact(self.db, ward_id=ward_id, event_type="planning.confirmed",
                              source_type="plan_draft", source_id=draft.id, source_version=draft.version,
                              payload={"schedule_id": schedule.id, "schedule_version": schedule.version,
                                       "task_count": len(selected)})
        self.db.add(OutboxEvent(aggregate_type="daily_schedule", aggregate_id=schedule.id,
                               event_type="PlanConfirmed.v1", payload={"schema_version": "PlanConfirmed.v1",
                               "ward_id": ward_id, "schedule_id": schedule.id, "version": schedule.version,
                               "items": deepcopy(selected)}))
        self.db.flush()
        return schedule
