from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.application.commands.plan_intake import (
    PlanIntakeInput,
    PlanIntakeItem,
    PlanIntakeResult,
    _prompt,
    require_missing_duration_clarification,
)
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.persistence.models import Task
from tests.support.factories import create_daily_schedule, create_task, create_ward


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


def test_missing_task_duration_stays_pending_instead_of_defaulting_to_30_minutes(db):
    """计划解析缺少预计时长时，必须追问而不是臆定 30 分钟。"""
    ward = create_ward(db)
    item = PlanIntakeItem(title="整理错题", new_task=True)

    assert item.planned_minutes is None

    draft = PlanningDomainService(db).save_draft(
        ward.id,
        date(2026, 9, 12),
        [item.model_dump(mode="json")],
        pending_fields=["planned_minutes"],
    )
    assert draft.pending_fields == ["planned_minutes"]
    assert draft.items == []
    batch = draft.working_state["active_clarification_batch"]
    assert batch["slots"][0]["title"] == "整理错题"


def test_llm_structured_duration_updates_resolve_slots_and_create_task_pool_records(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id, date(2026, 9, 18), [
            {"new_task": True, "title": "数学试卷", "planned_minutes": None},
            {"new_task": True, "title": "英语作业", "planned_minutes": None},
        ], pending_fields=["planned_minutes"],
    )
    assert len(draft.working_state["active_clarification_batch"]["slots"]) == 2

    slots = draft.working_state["active_clarification_batch"]["slots"]
    resolved = service.resolve_duration_clarification(
        ward_id=ward.id, plan_date=date(2026, 9, 18),
        answers=[{"slot_id": slots[0]["slot_id"], "value": "30分钟"},
                 {"slot_id": slots[1]["slot_id"], "value": "50分钟"}],
    )
    assert resolved is not None
    updated, count = resolved
    assert count == 2
    assert updated.pending_fields == []
    assert "active_clarification_batch" not in updated.working_state
    assert {(task.title, task.planned_minutes) for task in db.query(Task).filter_by(ward_id=ward.id)} == {
        ("数学试卷", 30), ("英语作业", 50),
    }


def test_service_never_interprets_bare_text_for_multiple_duration_slots(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id, date(2026, 9, 18), [
            {"new_task": True, "title": "数学试卷", "planned_minutes": None},
            {"new_task": True, "title": "英语作业", "planned_minutes": None},
        ], pending_fields=["planned_minutes"],
    )
    result = service.resolve_duration_clarification(ward_id=ward.id, plan_date=date(2026, 9, 18))
    assert result == (draft, 0)
    assert len(draft.working_state["active_clarification_batch"]["slots"]) == 2
    assert db.query(Task).filter_by(ward_id=ward.id).count() == 0


def test_structured_duration_update_binds_to_the_issued_task(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="数学试卷", planned_minutes=None)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id, date(2026, 9, 18),
        [{"assignment_id": task.id, "new_task": False, "title": task.title, "planned_minutes": None}],
        pending_fields=["planned_minutes"],
    )
    slot_id = draft.working_state["active_clarification_batch"]["slots"][0]["slot_id"]
    updated, count = service.resolve_duration_clarification(
        ward_id=ward.id, plan_date=date(2026, 9, 18),
        answers=[{"slot_id": slot_id, "value": "30分钟"}],
    )
    assert count == 1
    assert updated.pending_fields == []
    assert task.planned_minutes == 30


def test_scheduling_turn_preserves_unresolved_duration_slot_and_can_become_confirmable(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="英语听力", planned_minutes=None)
    service = PlanningDomainService(db)
    first = service.save_draft(
        ward.id, date(2026, 9, 18),
        [{"assignment_id": task.id, "new_task": False, "title": task.title, "planned_minutes": None}],
        pending_fields=["planned_minutes"],
    )
    slot_id = first.working_state["active_clarification_batch"]["slots"][0]["slot_id"]

    # A following scheduling turn must not erase its duration target.
    second = service.save_draft(
        ward.id, date(2026, 9, 18),
        [{"assignment_id": task.id, "new_task": False, "title": task.title,
          "planned_minutes": None, "start_at": "2026-09-18T19:00:00"}],
        pending_fields=["planned_minutes"],
    )
    assert second.working_state["active_clarification_batch"]["slots"][0]["slot_id"] == slot_id
    updated, count = service.resolve_duration_clarification(
        ward_id=ward.id, plan_date=date(2026, 9, 18),
        answers=[{"slot_id": slot_id, "value": "30分钟"}],
    )
    assert count == 1
    assert service.plan_draft_view(ward.id, updated.id)["confirm_enabled"] is True


def test_missing_task_duration_generates_a_direct_clarification_question():
    result = require_missing_duration_clarification(PlanIntakeResult(
        assistant_text="已整理任务。",
        items=[PlanIntakeItem(title="整理错题", new_task=True)],
        ready_to_confirm=True,
    ))

    assert result.ready_to_confirm is False
    assert result.clarification_required is True
    assert result.questions == ["“整理错题” 预计需要多长时间？"]
    assert result.assistant_text == "还需要补充预计时长：“整理错题” 预计需要多长时间？"


def test_plan_intake_prompt_renders_slot_update_example_literally():
    prompt = _prompt(
        {"id": "ward-1", "display_name": "小读"},
        [],
        PlanIntakeInput(
            content="英语听力三十分钟",
            clarification_slots=[{"slot_id": "duration:task-1", "field": "planned_minutes"}],
        ),
    )

    assert '{slot_id, value:"30分钟"}' in prompt


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


def test_same_unbound_start_time_for_multiple_tasks_requires_target_clarification(db):
    ward = create_ward(db)
    math = create_task(db, ward=ward, title="数学", planned_minutes=25)
    english = create_task(db, ward=ward, title="英语", planned_minutes=25)
    draft = PlanningDomainService(db).save_draft(
        ward.id, date(2026, 9, 17), [
            {"assignment_id": math.id, "new_task": False, "title": math.title,
             "planned_minutes": 25, "start_at": "2026-09-17T18:00:00"},
            {"assignment_id": english.id, "new_task": False, "title": english.title,
             "planned_minutes": 25, "start_at": "2026-09-17T18:00:00"},
        ],
    )

    view = PlanningDomainService(db).plan_draft_view(ward.id, draft.id)
    assert view["confirm_enabled"] is False
    assert view["pending_fields"] == ["ambiguous_target_task"]
    assert all(item.get("start_at") is None for item in view["items"])


def test_after_task_intent_derives_a_non_overlapping_slot(db):
    ward = create_ward(db)
    math = create_task(db, ward=ward, title="数学", planned_minutes=25)
    english = create_task(db, ward=ward, title="英语", planned_minutes=20)
    draft = PlanningDomainService(db).save_draft(
        ward.id, date(2026, 9, 17), [
            {"assignment_id": math.id, "new_task": False, "title": math.title,
             "planned_minutes": 25, "start_at": "2026-09-17T18:00:00"},
            {"assignment_id": english.id, "new_task": False, "title": english.title,
             "planned_minutes": 20, "after_assignment_id": math.id},
        ],
    )

    view = PlanningDomainService(db).plan_draft_view(ward.id, draft.id)
    english_item = next(item for item in view["items"] if item["assignment_id"] == english.id)
    assert english_item["start_at"] == "2026-09-17T18:25:00"
    assert english_item["slot_source"] == "deterministic_derived"
    assert view["confirm_enabled"] is True


def test_unique_existing_task_reference_becomes_a_patch_not_a_new_task(db):
    ward = create_ward(db)
    listening = create_task(db, ward=ward, title="英语听力", planned_minutes=30)
    service = PlanningDomainService(db)

    items, pending = service.resolve_task_references(ward.id, [{
        "task_reference": "英语听力", "title": "英语听力", "new_task": True,
        "start_at": "2026-09-18T19:00:00",
    }])

    assert pending == set()
    assert items == [{
        "task_reference": "英语听力", "title": "英语听力", "new_task": False,
        "start_at": "2026-09-18T19:00:00", "assignment_id": listening.id,
        "details": listening.details, "planned_minutes": 30,
    }]
    draft = service.save_draft(ward.id, date(2026, 9, 18), items)
    assert db.query(Task).filter_by(ward_id=ward.id).count() == 1
    assert next(item for item in draft.items if item["assignment_id"] == listening.id)["start_at"] == "2026-09-18T19:00:00"


def test_exact_item_title_falls_back_when_model_reference_is_not_usable(db):
    ward = create_ward(db)
    listening = create_task(db, ward=ward, title="英语听力", planned_minutes=30)

    items, pending = PlanningDomainService(db).resolve_task_references(ward.id, [{
        "task_reference": "英语的听力作业",  # Model wording may be less precise than its title field.
        "title": "英语听力",
        "start_at": "2026-09-18T19:30:00",
    }])

    assert pending == set()
    assert items[0]["assignment_id"] == listening.id
    assert items[0]["new_task"] is False


def test_ambiguous_task_reference_never_creates_a_same_name_task(db):
    ward = create_ward(db)
    create_task(db, ward=ward, title="英语听力", planned_minutes=30)
    create_task(db, ward=ward, title="英语阅读", planned_minutes=30)
    service = PlanningDomainService(db)

    items, pending = service.resolve_task_references(ward.id, [{
        "task_reference": "英语", "title": "英语", "planned_minutes": 30,
        "start_at": "2026-09-18T19:00:00",
    }])

    assert items == []
    assert pending == {"ambiguous_target_task"}
    draft = service.save_draft(ward.id, date(2026, 9, 18), items, pending_fields=list(pending))
    assert db.query(Task).filter_by(ward_id=ward.id).count() == 2
    assert draft.pending_fields == ["ambiguous_target_task"]
