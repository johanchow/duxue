from __future__ import annotations

from datetime import date
import pytest
from fastapi import HTTPException

from app.application.workflows.planning_domain_service import PlanningDomainService, MAX_DAILY_MINUTES
from tests.support.factories import create_guardian, create_ward, create_task, create_daily_schedule


def test_cannot_exceed_max_daily_minutes(db):
    """草稿计划单日总时长不能超过 480 分钟上限。"""
    ward = create_ward(db)
    service = PlanningDomainService(db)
    items = [
        {"new_task": True, "title": "任务1", "planned_minutes": 300},
        {"new_task": True, "title": "任务2", "planned_minutes": 200},
    ]
    with pytest.raises(HTTPException) as exc:
        service.save_draft(ward.id, date(2026, 9, 12), items)
    assert exc.value.status_code == 400
    assert "上限" in exc.value.detail


def test_invalid_task_source_rejected(db):
    """不能混淆新任务与已有任务标识，也不能引用不存在或属于其他学生任务。"""
    ward1 = create_ward(db, display_name="学生1")
    ward2 = create_ward(db, display_name="学生2")
    task_other = create_task(db, ward=ward2, title="他人的任务")

    service = PlanningDomainService(db)

    # 1. new_task=True 却传了 assignment_id
    with pytest.raises(HTTPException) as exc1:
        service.save_draft(
            ward1.id,
            date(2026, 9, 12),
            [{"new_task": True, "assignment_id": task_other.id, "title": "无效任务", "planned_minutes": 30}],
        )
    assert exc1.value.status_code == 400

    # 2. new_task=False 却引用了属于 ward2 的 task
    with pytest.raises(HTTPException) as exc2:
        service.save_draft(
            ward1.id,
            date(2026, 9, 12),
            [{"new_task": False, "assignment_id": task_other.id, "title": "别人的任务", "planned_minutes": 30}],
        )
    assert exc2.value.status_code == 400


def test_task_duration_and_title_validation(db):
    """任务标题不能为空白，时长必须在 1~480 分钟之间。"""
    ward = create_ward(db)
    service = PlanningDomainService(db)

    # 空标题
    with pytest.raises(HTTPException) as exc1:
        service.save_draft(
            ward.id,
            date(2026, 9, 12),
            [{"new_task": True, "title": "   ", "planned_minutes": 30}],
        )
    assert exc1.value.status_code == 400

    # 时长 0 分钟
    with pytest.raises(HTTPException) as exc2:
        service.save_draft(
            ward.id,
            date(2026, 9, 12),
            [{"new_task": True, "title": "有效标题", "planned_minutes": 0}],
        )
    assert exc2.value.status_code == 400


def test_cannot_confirm_draft_with_pending_fields(db):
    """草稿中包含 pending_fields（待确认信息）时不能确认生效。"""
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id,
        date(2026, 9, 12),
        [{"new_task": True, "title": "数学口算", "planned_minutes": 20}],
        pending_fields=["planned_minutes"],
    )
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.confirm(ward.id, draft.id)
    assert exc.value.status_code == 409
    assert "待确认" in exc.value.detail


def test_conflict_on_base_schedule_version_mismatch(db):
    """若在草稿协商期间基准计划发生变更（版本增加），确认时必须拦截冲突并提示重新审阅。"""
    ward = create_ward(db)
    schedule = create_daily_schedule(db, ward=ward, schedule_date=date(2026, 9, 12), version=1)
    db.commit()

    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id,
        date(2026, 9, 12),
        [{"new_task": True, "title": "听写课文", "planned_minutes": 15}],
    )
    db.commit()

    # 模拟外部变更递增了 schedule version
    schedule.version = 2
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.confirm(ward.id, draft.id)
    assert exc.value.status_code == 409
    assert "计划已变化" in exc.value.detail
