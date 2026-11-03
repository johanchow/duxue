from datetime import date

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.persistence.models import StudySession, Task
from tests.support.factories import create_ward, create_task


def test_title_only_can_register_confirm_without_starting(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id,
        date(2026, 11, 3),
        [
            {"new_task": True, "title": "数学"},
            {"new_task": True, "title": "英语"},
        ],
    )
    view = service.plan_draft_view(ward.id, draft.id)
    assert view["confirm_enabled"]
    schedule = service.confirm(ward.id, draft.id, draft.version)
    assert [i["title"] for i in schedule.items] == ["数学", "英语"]
    assert all(
        i.get("start_at") is None and i.get("planned_minutes") is None
        for i in schedule.items
    )
    assert db.query(StudySession).count() == 0


def test_guardian_unselected_task_never_requires_reason(db):
    ward = create_ward(db)
    guardian_task = create_task(db, ward=ward, title="语文")
    draft = PlanningDomainService(db).apply_operations(
        ward.id,
        date(2026, 11, 3),
        [
            {"kind": "create", "title": "数学"},
        ],
        command_id="add-math",
    )
    service = PlanningDomainService(db)
    view = service.plan_draft_view(ward.id, draft.id)
    assert view["confirm_enabled"]
    assert view["pending_fields"] == []
    schedule = service.confirm(ward.id, draft.id, draft.version)
    assert [i["title"] for i in schedule.items] == ["数学"]
    assert db.get(Task, guardian_task.id).schedule_id is None


def test_order_is_not_a_derived_clock(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.apply_operations(
        ward.id,
        date(2026, 11, 3),
        [
            {
                "kind": "create",
                "title": "数学",
                "planned_minutes": 20,
                "start_at": "2026-11-03T19:00:00+08:00",
            },
            {"kind": "create", "title": "英语", "after_task_reference": "数学"},
        ],
        command_id="order",
    )
    assert service.plan_draft_view(ward.id, draft.id)["confirm_enabled"]
    schedule = service.confirm(ward.id, draft.id, draft.version)
    assert [i["title"] for i in schedule.items] == ["数学", "英语"]
    assert schedule.items[1].get("start_at") is None


def test_started_task_history_is_protected_but_unstarted_item_can_be_revised(db):
    from tests.support.factories import create_study_session

    ward = create_ward(db)
    service = PlanningDomainService(db)
    day = date(2026, 11, 3)
    draft = service.save_draft(
        ward.id,
        day,
        [{"new_task": True, "title": "数学"}, {"new_task": True, "title": "英语"}],
    )
    service.confirm(ward.id, draft.id, draft.version)
    math = db.query(Task).filter_by(title="数学").one()
    create_study_session(db, ward=ward, task=math)
    revision = service.apply_operations(
        ward.id,
        day,
        [{"kind": "update", "references": ["英语"], "planned_minutes": 20}],
        command_id="edit-next",
    )
    service.confirm(ward.id, revision.id, revision.version)
    assert math.status == "scheduled" and math.planned_minutes is None
    assert db.query(Task).filter_by(title="英语").one().planned_minutes == 20


def test_plain_estimate_is_never_a_sprint(db):
    from app.infrastructure.persistence.models import Sprint

    ward = create_ward(db)
    service = PlanningDomainService(db)
    day = date(2026, 11, 3)
    draft = service.save_draft(
        ward.id,
        day,
        [
            {
                "new_task": True,
                "title": "数学",
                "planned_minutes": 20,
                "start_at": "2026-11-03T19:00:00+08:00",
            }
        ],
    )
    service.confirm(ward.id, draft.id, draft.version)
    assert db.query(Sprint).count() == 0


def test_timebox_duration_is_distinct_from_completion_estimate(db):
    from app.infrastructure.persistence.models import Sprint

    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.apply_operations(
        ward.id,
        date(2026, 11, 3),
        [
            {
                "kind": "create",
                "title": "数学",
                "planned_minutes": 20,
                "duration_kind": "timebox",
            }
        ],
        command_id="timebox",
    )
    task = db.query(Task).one()
    assert task.duration_kind == "timebox" and task.duration_source == "ward"
    service.confirm(ward.id, draft.id, draft.version)
    assert db.query(Sprint).count() == 0


def test_start_clock_is_date_checked_even_without_duration(db):
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(
        ward.id,
        date(2026, 11, 3),
        [{"new_task": True, "title": "英语", "start_at": "2026-11-04T19:00:00+08:00"}],
    )
    view = service.plan_draft_view(ward.id, draft.id)
    assert not view["confirm_enabled"]
    assert view["conflicts"][0]["code"] == "wrong_plan_date"
