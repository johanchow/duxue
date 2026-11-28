"""Task status follows the planning lifecycle, not the study session."""
from datetime import date

from app.infrastructure.persistence.models import (
    DailySchedule,
    StudySession,
    StudySessionInterval,
    Task,
)
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_daily_schedule, create_task, create_ward

TODAY = date(2026, 9, 26)
PAST = date(2026, 9, 21)


def _headers(ward):
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    return {"Authorization": f"Bearer {token}"}


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
