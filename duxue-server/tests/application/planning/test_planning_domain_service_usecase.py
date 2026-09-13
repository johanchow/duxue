from __future__ import annotations

from datetime import date
import pytest
from fastapi import HTTPException

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.persistence.models import DailySchedule, OutboxEvent, PlanDraft, Task
from tests.support.factories import create_ward, create_task


def test_save_draft_and_confirm_workflow_lifecycle(db):
    """计划用例完整生命周期：创建任务 -> 保存草稿 -> 确认草稿 -> 正式排程与 Outbox 发布。"""
    ward = create_ward(db)
    existing_task = create_task(db, ward=ward, title="已有数学任务", planned_minutes=40)
    db.commit()

    service = PlanningDomainService(db)
    plan_date = date(2026, 9, 12)

    # 1. 保存草稿（包含一个已有任务和一个新任务）
    draft = service.save_draft(
        ward_id=ward.id,
        plan_date=plan_date,
        items=[
            {"new_task": False, "assignment_id": existing_task.id, "title": existing_task.title, "planned_minutes": 45},
            {"new_task": True, "title": "新增英语听力", "planned_minutes": 25},
        ],
    )
    db.commit()

    assert draft.status == "active"
    assert draft.version == 1
    # 此时正式日程尚未创建，已有任务的 schedule_id 仍为空
    assert existing_task.schedule_id is None

    # 2. 确认草稿
    schedule = service.confirm(ward_id=ward.id, draft_id=draft.id)
    db.commit()

    assert schedule.status == "confirmed"
    assert schedule.schedule_date == plan_date

    # 验证已有任务状态更新
    updated_existing = db.get(Task, existing_task.id)
    assert updated_existing.schedule_id == schedule.id
    assert updated_existing.position == 0
    assert updated_existing.planned_minutes == 45

    # 验证新增任务创建
    new_tasks = db.query(Task).filter(Task.ward_id == ward.id, Task.title == "新增英语听力").all()
    assert len(new_tasks) == 1
    assert new_tasks[0].schedule_id == schedule.id
    assert new_tasks[0].position == 1

    # 验证 Outbox 事先发布事实
    outbox = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "LearningFactRecorded.v1")
        .first()
    )
    assert outbox is not None
    assert outbox.payload["event_type"] == "planning.confirmed"


def test_confirm_draft_is_idempotent(db):
    """重复确认已确认的草稿，应幂等返回已有 Schedule，不重复变更。"""
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id,
        date(2026, 9, 12),
        [{"new_task": True, "title": "科学小实验", "planned_minutes": 30}],
    )
    db.commit()

    first_sched = service.confirm(ward.id, draft.id)
    db.commit()
    second_sched = service.confirm(ward.id, draft.id)
    db.commit()

    assert first_sched.id == second_sched.id


def test_cannot_confirm_other_wards_draft(db):
    """不能确认属于其他学生的草稿。"""
    ward1 = create_ward(db, display_name="学生A")
    ward2 = create_ward(db, display_name="学生B")
    service = PlanningDomainService(db)
    draft1 = service.save_draft(
        ward1.id,
        date(2026, 9, 12),
        [{"new_task": True, "title": "A的计划", "planned_minutes": 20}],
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.confirm(ward_id=ward2.id, draft_id=draft1.id)
    assert exc.value.status_code == 404
