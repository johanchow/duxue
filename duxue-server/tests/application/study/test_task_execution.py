from datetime import datetime, timedelta, timezone

from app.application.commands import task_execution
from app.application.commands.task_execution import TaskExecutionService
from app.infrastructure.persistence.models import StudySession, StudySessionInterval
from tests.support.factories import create_ward, create_task, create_study_session

AT = datetime(2026, 11, 3, 11, tzinfo=timezone.utc)


def test_switch_pause_resume_and_end_preserve_task_and_count_only_intervals(
    db, monkeypatch
):
    ward = create_ward(db)
    math, english = create_task(db, ward=ward), create_task(db, ward=ward)
    session = create_study_session(db, ward=ward, task=math)
    session.started_at = AT
    db.add(StudySessionInterval(study_session_id=session.id, started_at=AT))
    db.flush()
    monkeypatch.setattr(task_execution, "now", lambda: AT + timedelta(minutes=5))
    service = TaskExecutionService(db)
    second = service.execute(ward.id, english.id, "start")["session"]
    assert session.status == "paused" and session.active_seconds == 300
    assert session.pause_count == 1
    assert (
        db.query(StudySession).filter_by(ward_id=ward.id, status="active").count() == 1
    )
    monkeypatch.setattr(task_execution, "now", lambda: AT + timedelta(minutes=20))
    service.execute(ward.id, math.id, "resume")
    assert db.get(StudySession, second["id"]).status == "paused"
    # Force deterministic interval start; ORM defaults use wall time.
    live = (
        db.query(StudySessionInterval)
        .filter_by(study_session_id=session.id, ended_at=None)
        .one()
    )
    live.started_at = AT + timedelta(minutes=20)
    monkeypatch.setattr(task_execution, "now", lambda: AT + timedelta(minutes=22))
    service.execute(ward.id, math.id, "end")
    assert session.status == "abandoned" and session.completion_reason == "ward_stopped"
    assert session.active_seconds == 420
    assert math.status == english.status == "pool"
    assert service.execute(ward.id, math.id, "time")["active_seconds"] == 420
