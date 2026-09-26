"""Task status follows the planning lifecycle, not the study session."""
from datetime import date

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.persistence.models import DailySchedule, StudySession, StudySessionInterval, Task
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_daily_schedule, create_task, create_ward

TODAY = date(2026, 9, 26)
PAST = date(2026, 9, 21)


def _headers(ward):
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    return {"Authorization": f"Bearer {token}"}


def test_confirm_marks_scheduled_and_removal_returns_to_pool(db, monkeypatch):
    monkeypatch.setattr(
        "app.application.workflows.planning_operations.local_plan_date", lambda: PAST)
    ward = create_ward(db)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, PAST, [{
        "new_task": True, "title": "数学的挑战题", "planned_minutes": 30,
        "start_at": "2026-09-21T15:00:00",
    }])
    task = db.query(Task).one()
    assert task.status == "pool"
    service.confirm(ward.id, draft.id, draft.version)
    assert task.status == "scheduled"
    assert task.schedule_id is not None

    revision = service.apply_operations(ward.id, PAST, [
        {"kind": "create", "title": "英语听力", "planned_minutes": 20,
         "start_at": "2026-09-21T16:00:00"},
        {"kind": "defer", "references": ["数学的挑战题"], "reason": "今天不做"},
    ], command_id="keep-english")
    service.confirm(ward.id, revision.id, revision.version)
    assert task.status == "pool"
    assert task.schedule_id is None
    history = db.query(DailySchedule).filter_by(schedule_date=PAST).one()
    assert history.history
    english = db.query(Task).filter_by(title="英语听力").one()
    assert english.status == "scheduled"


def test_past_scheduled_task_can_be_arranged_today(db, monkeypatch):
    monkeypatch.setattr(
        "app.application.workflows.planning_operations.local_plan_date", lambda: TODAY)
    ward = create_ward(db)
    schedule = create_daily_schedule(db, ward=ward, schedule_date=PAST, status="confirmed")
    task = create_task(
        db, ward=ward, title="数学的挑战题", planned_minutes=30,
        status="scheduled", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": task.id, "title": task.title, "planned_minutes": 30,
        "start_at": "2026-09-21T19:00:00", "end_at": "2026-09-21T19:30:00",
    }]
    db.flush()
    service = PlanningDomainService(db)

    draft = service.apply_operations(ward.id, TODAY, [{
        "kind": "schedule", "references": ["数学的挑战题"],
        "start_at": "2026-09-26T15:00:00",
    }], command_id="move-today")

    assert task.status == "pool"
    assert task.schedule_id is None
    assert schedule.items[0]["assignment_id"] == task.id
    result = next(item for item in draft.working_state["operation_results"]
                  if item["kind"] == "schedule")
    assert result["status"] == "applied"
    assert task.id in result["task_ids"]


def test_completed_task_stays_off_the_new_day(db, monkeypatch):
    monkeypatch.setattr(
        "app.application.workflows.planning_operations.local_plan_date", lambda: TODAY)
    ward = create_ward(db)
    schedule = create_daily_schedule(db, ward=ward, schedule_date=PAST, status="confirmed")
    task = create_task(
        db, ward=ward, title="数学的挑战题", status="completed", schedule_id=schedule.id)
    service = PlanningDomainService(db)
    released = service.release_unfinished_tasks(ward.id, TODAY)
    assert released == 0
    assert task.status == "completed"
    assert task.schedule_id == schedule.id


def test_finish_session_completes_the_bound_task_once(client, db):
    ward = create_ward(db, display_name="小宇", session_version=1)
    task = create_task(db, ward=ward, title="数学的挑战题", status="pool")
    session = StudySession(ward_id=ward.id, task_id=task.id, status="active")
    db.add(session)
    db.flush()
    db.add(StudySessionInterval(study_session_id=session.id))
    db.commit()

    response = client.post(
        f"/sessions/{session.id}/finish", headers=_headers(ward),
        json={"active_seconds": 20})
    assert response.status_code == 200
    db.refresh(task)
    assert task.status == "completed"

    again = client.post(
        f"/sessions/{session.id}/finish", headers=_headers(ward),
        json={"active_seconds": 20})
    assert again.status_code == 409
    db.refresh(task)
    assert task.status == "completed"


def test_listing_assignments_releases_past_tasks_into_the_pool(client, db):
    ward = create_ward(db, display_name="小宇", session_version=1)
    schedule = create_daily_schedule(db, ward=ward, schedule_date=PAST, status="confirmed")
    task = create_task(
        db, ward=ward, title="英语的典范故事阅读", status="scheduled", schedule_id=schedule.id)
    db.commit()

    listed = client.get(f"/wards/{ward.id}/assignments", headers=_headers(ward))
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task.id
    db.refresh(task)
    assert task.status == "pool"
    assert task.schedule_id is None
    assert db.get(DailySchedule, schedule.id).status == "confirmed"
