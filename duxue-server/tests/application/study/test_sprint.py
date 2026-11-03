from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from app.application.commands.sprint import SprintService
from app.infrastructure.persistence.models import Sprint, StudySession, Task
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward, create_task, create_study_session

AT = datetime(2026, 11, 3, 11, tzinfo=timezone.utc)


def test_sprint_pauses_resumes_and_expires_without_completing_task(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward)
    session = create_study_session(db, ward=ward, task=task)
    row = SprintService(db, moment=AT).execute(
        ward.id,
        "start",
        "create",
        topic="数学",
        target_minutes=20,
        task_id=task.id,
        study_session_id=session.id,
    )["sprint"]
    paused = SprintService(db, moment=AT + timedelta(minutes=5)).execute(
        ward.id, "pause", "pause", sprint_id=row["id"], expected_version=row["version"]
    )["sprint"]
    assert paused["elapsed_seconds"] == 300
    resumed = SprintService(db, moment=AT + timedelta(minutes=15)).execute(
        ward.id,
        "resume",
        "resume",
        sprint_id=row["id"],
        expected_version=paused["version"],
    )["sprint"]
    assert resumed["elapsed_seconds"] == 300
    assert (
        SprintService(db, moment=AT + timedelta(minutes=40)).current(ward.id)["sprint"]
        is None
    )
    sprint = db.get(Sprint, row["id"])
    assert sprint.study_session_id == session.id
    assert sprint.elapsed_seconds == 1200 and sprint.status == "elapsed"
    assert task.status == "pool" and session.status == "active"


def test_idempotency_versions_and_single_live_round(db):
    ward = create_ward(db)
    service = SprintService(db, moment=AT)
    first = service.execute(ward.id, "same", "create", topic="阅读", target_minutes=10)
    assert (
        service.execute(ward.id, "same", "create", topic="阅读", target_minutes=10)
        == first
    )
    with pytest.raises(HTTPException):
        service.execute(ward.id, "same", "create", topic="数学", target_minutes=10)
    with pytest.raises(HTTPException):
        service.execute(ward.id, "second", "create", topic="数学", target_minutes=10)
    db.rollback()


def test_early_end_is_not_failure_and_future_round_does_not_start(db):
    ward = create_ward(db)
    service = SprintService(db, moment=AT)
    ready = service.execute(
        ward.id,
        "future",
        "prepare",
        topic="阅读",
        target_minutes=10,
        planned_start_at=AT + timedelta(hours=1),
    )["sprint"]
    assert ready["status"] == "ready" and ready["started_at"] is None
    assert service.current(ward.id)["sprint"] is None
    active = service.execute(
        ward.id,
        "now",
        "start",
        sprint_id=ready["id"],
        expected_version=ready["version"],
    )["sprint"]
    ended = service.execute(
        ward.id,
        "stop",
        "end",
        sprint_id=active["id"],
        expected_version=active["version"],
    )["sprint"]
    assert ended["status"] == "ended" and ended["end_reason"] == "end"
    assert db.query(StudySession).count() == 0 and db.query(Task).count() == 0


def test_sprint_api_authorization_and_null_times(client, db):
    ward, other = create_ward(db), create_ward(db)
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    }
    response = client.post(
        "/sprints",
        headers=headers,
        json={
            "command_id": "start",
            "topic": "阅读",
            "target_minutes": 10,
            "action": "create",
        },
    )
    assert response.status_code == 201
    row = response.json()["sprint"]
    alien = {
        "Authorization": "Bearer "
        + create_access_token(user_id=other.id, role="ward", ward_session_version=1)
    }
    assert (
        client.post(
            f"/sprints/{row['id']}/commands",
            headers=alien,
            json={"action": "end", "expected_version": row["version"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/sprints", headers=headers, json={"topic": "阅读", "target_minutes": 10}
        ).status_code
        == 422
    )


def test_cross_day_does_not_reopen_forgotten_round(db):
    ward = create_ward(db)
    late = AT.replace(hour=15, minute=55)
    row = SprintService(db, moment=late).execute(
        ward.id, "late", "create", topic="阅读", target_minutes=20
    )["sprint"]
    assert (
        SprintService(db, moment=late + timedelta(minutes=6)).current(ward.id)["sprint"]
        is None
    )
    saved = db.get(Sprint, row["id"])
    assert saved.status == "ended" and saved.end_reason == "day_rollover"
    assert saved.elapsed_seconds == 300


def test_future_invitation_is_once_and_does_not_start_round(db):
    ward = create_ward(db)
    ready = SprintService(db, moment=AT).execute(
        ward.id,
        "future",
        "prepare",
        topic="阅读",
        target_minutes=10,
        planned_start_at=AT + timedelta(minutes=5),
    )["sprint"]
    service = SprintService(db, moment=AT + timedelta(minutes=5))
    notice = service.current(ward.id)["notice"]
    assert notice["status"] == "ready"
    service.execute(
        ward.id,
        "seen",
        "claim_notice",
        sprint_id=ready["id"],
        expected_version=ready["version"],
    )
    assert service.current(ward.id)["notice"] is None
    assert db.get(Sprint, ready["id"]).started_at is None


def test_guardian_cannot_start_a_sprint_and_version_change_is_rejected(client, db):
    from tests.support.factories import create_guardian

    guardian = create_guardian(db)
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=guardian.id, role="guardian")
    }
    assert (
        client.post(
            "/sprints",
            headers=headers,
            json={"topic": "阅读", "target_minutes": 20, "action": "create"},
        ).status_code
        == 403
    )
    ward = create_ward(db)
    service = SprintService(db, moment=AT)
    row = service.execute(ward.id, "start", "create", topic="阅读", target_minutes=10)[
        "sprint"
    ]
    paused = service.execute(
        ward.id, "pause", "pause", sprint_id=row["id"], expected_version=row["version"]
    )["sprint"]
    with pytest.raises(HTTPException) as error:
        service.execute(
            ward.id,
            "stale",
            "resume",
            sprint_id=row["id"],
            expected_version=row["version"],
        )
    assert error.value.status_code == 409
    assert paused["status"] == "paused"


def test_data_erasure_removes_sprints_and_command_receipts(client, db):
    from tests.support.factories import create_guardian
    from app.infrastructure.persistence.models import SprintCommand

    guardian = create_guardian(db)
    ward = create_ward(db, guardian=guardian)
    task = create_task(db, ward=ward)
    session = create_study_session(db, ward=ward, task=task)
    SprintService(db, moment=AT).execute(
        ward.id,
        "start",
        "create",
        topic="阅读",
        target_minutes=10,
        task_id=task.id,
        study_session_id=session.id,
    )
    db.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=guardian.id, role="guardian")
    }
    assert client.delete(f"/wards/{ward.id}/data", headers=headers).status_code == 204
    assert db.query(Sprint).filter_by(ward_id=ward.id).count() == 0
    assert db.query(SprintCommand).filter_by(ward_id=ward.id).count() == 0


def test_sprint_rejects_another_wards_session_and_mismatched_task(db):
    ward, other = create_ward(db), create_ward(db)
    foreign = create_study_session(db, ward=other, task=create_task(db, ward=other))
    own_task = create_task(db, ward=ward)
    own_session = create_study_session(db, ward=ward, task=own_task)
    unrelated_task = create_task(db, ward=ward)
    for session_id, task_id in [
        (foreign.id, None),
        (own_session.id, unrelated_task.id),
    ]:
        with pytest.raises(HTTPException) as error:
            SprintService(db, moment=AT).execute(
                ward.id,
                "bad-binding",
                "create",
                topic="阅读",
                target_minutes=10,
                task_id=task_id,
                study_session_id=session_id,
            )
        assert error.value.status_code == 404
    assert db.query(Sprint).count() == 0
