from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import GuardianWard, Task
from tests.support.factories import (
    create_guardian,
    create_ward,
    create_task,
    create_daily_schedule,
    create_device,
)


def test_guardian_ward_binding_integrity(db):
    """监护人与学生绑定关系建立与多对多关联查询。"""
    guardian = create_guardian(db, name="王家长", email="wang@example.com")
    ward1 = create_ward(db, guardian=guardian, display_name="大宝")
    ward2 = create_ward(db, guardian=guardian, display_name="二宝")
    db.commit()

    bound_wards = (
        db.query(GuardianWard)
        .filter(GuardianWard.guardian_id == guardian.id)
        .all()
    )
    assert len(bound_wards) == 2
    ward_ids = {bw.ward_id for bw in bound_wards}
    assert ward_ids == {ward1.id, ward2.id}


def test_task_schedule_assignment_relationship(db):
    """任务与每日计划关联：在任务池时 schedule_id 为空；分配到计划后建立关联。"""
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="生字本练习")
    db.commit()

    # 初始状态在任务池
    assert task.schedule_id is None

    # 分配进今日排程
    schedule = create_daily_schedule(db, ward=ward, schedule_date=date(2026, 9, 12))
    task.schedule_id = schedule.id
    task.position = 0
    db.commit()

    # 查询排程下的所有任务
    tasks_in_schedule = db.query(Task).filter(Task.schedule_id == schedule.id).all()
    assert len(tasks_in_schedule) == 1
    assert tasks_in_schedule[0].id == task.id


def test_device_binding_lifecycle_state(db):
    """设备从生成邀请码到绑定在线的状态变更。"""
    ward = create_ward(db)
    device = create_device(db, ward=ward, invite_code="987654", status="offline")
    db.commit()

    assert device.status == "offline"
    assert device.invite_code == "987654"

    # 模拟设备绑定成功后
    device.status = "online"
    device.invite_code = None
    db.commit()

    reloaded = db.get(device.__class__, device.id)
    assert reloaded.status == "online"
    assert reloaded.invite_code is None
