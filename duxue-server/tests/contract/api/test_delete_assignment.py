"""Swipe-to-remove must delete the Task row, not only hide it in the client."""
from datetime import date

from app.infrastructure.persistence.models import DailySchedule, Task
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import (
    create_daily_schedule,
    create_study_session,
    create_task,
    create_ward,
)


def _ward_headers(ward):
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    return {"Authorization": f"Bearer {token}"}


def test_ward_delete_rejects_confirmed_schedule_item_without_review(client, db):
    ward = create_ward(db, display_name="小宇", session_version=1)
    schedule = create_daily_schedule(
        db, ward=ward, schedule_date=date(2026, 9, 18), status="confirmed")
    task = create_task(db, ward=ward, title="英语听力", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": task.id, "title": "英语听力",
        "planned_minutes": 30, "start_at": "2026-09-18T19:00:00",
    }]
    db.commit()

    response = client.delete(
        f"/wards/{ward.id}/assignments/{task.id}", headers=_ward_headers(ward))

    assert response.status_code == 409
    assert db.get(Task, task.id) is not None
    remaining = db.get(DailySchedule, schedule.id)
    assert remaining.items[0]["assignment_id"] == task.id
    listed = client.get(f"/wards/{ward.id}/assignments", headers=_ward_headers(ward))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [task.id]


def test_delete_rejects_task_with_study_history(client, db):
    ward = create_ward(db, display_name="小宇", session_version=1)
    task = create_task(db, ward=ward, title="数学试卷")
    create_study_session(db, ward=ward, task=task, status="completed")
    db.commit()

    response = client.delete(
        f"/wards/{ward.id}/assignments/{task.id}", headers=_ward_headers(ward))

    assert response.status_code == 409
    assert db.get(Task, task.id) is not None


def test_delete_other_wards_task_returns_404(client, db):
    owner = create_ward(db, display_name="小宇", session_version=1)
    other = create_ward(db, display_name="小安", session_version=1)
    task = create_task(db, ward=owner, title="新增作业")
    db.commit()

    response = client.delete(
        f"/wards/{other.id}/assignments/{task.id}", headers=_ward_headers(other))

    assert response.status_code == 404
    assert db.get(Task, task.id) is not None
