from datetime import timedelta

from app.application.commands.start_cue import StartCueService
from app.infrastructure.persistence.models import StudySessionInterval
from tests.application.study.test_start_cue import AT, _schedule
from tests.support.factories import create_study_session, create_task, create_ward


def test_estimate_does_not_authorize_rest_or_day_review(db):
    ward = create_ward(db)
    schedule = _schedule(db, ward)
    task = create_task(
        db, ward=ward, planned_minutes=20, status="scheduled", schedule_id=schedule.id
    )
    session = create_study_session(db, ward=ward, task=task, status="active")
    session.started_at = AT
    schedule.items = [
        {
            "slot_source": "ward_explicit",
            "assignment_id": task.id,
            "start_at": (AT + timedelta(minutes=10)).isoformat(),
            "planned_minutes": 20,
        }
    ]
    db.flush()
    assert StartCueService(db).sync(ward.id, moment=AT)["notifications"] == []


def test_scheduled_reminder_uses_agreed_clock_without_assuming_started(db):
    ward = create_ward(db)
    schedule = _schedule(db, ward)
    task = create_task(
        db, ward=ward, planned_minutes=20, status="scheduled", schedule_id=schedule.id
    )
    task.end_reminder_mode = "scheduled"
    schedule.items = [
        {
            "slot_source": "ward_explicit",
            "assignment_id": task.id,
            "start_at": (AT + timedelta(minutes=10)).isoformat(),
            "planned_minutes": 20,
        }
    ]
    db.flush()
    notes = StartCueService(db).sync(ward.id, moment=AT)["notifications"]
    end = next(n for n in notes if n["kind"] == "task_end")
    assert end["fire_at"] == (AT + timedelta(minutes=30)).isoformat()
    assert "约定" in end["body"]
    assert task.status == "scheduled"
    task.status = "completed"
    db.flush()
    assert StartCueService(db).sync(ward.id, moment=AT)["notifications"] == []


def test_elapsed_reminder_without_schedule_counts_only_execution_intervals(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, planned_minutes=20)
    task.end_reminder_mode = "elapsed"
    session = create_study_session(db, ward=ward, task=task, status="active")
    session.started_at = AT - timedelta(minutes=30)
    db.add_all(
        [
            StudySessionInterval(
                study_session_id=session.id,
                started_at=AT - timedelta(minutes=30),
                ended_at=AT - timedelta(minutes=25),
            ),
            StudySessionInterval(
                study_session_id=session.id, started_at=AT - timedelta(minutes=2)
            ),
        ]
    )
    db.flush()
    notes = StartCueService(db).sync(ward.id, moment=AT)["notifications"]
    assert len(notes) == 1
    assert notes[0]["fire_at"] == (AT + timedelta(minutes=13)).isoformat()
    session.status = "paused"
    db.flush()
    assert StartCueService(db).sync(ward.id, moment=AT)["notifications"] == []


def test_reminders_do_not_cross_wards_or_revive_after_cancellation(db):
    ward = create_ward(db)
    other = create_ward(db)
    task = create_task(db, ward=other, planned_minutes=20)
    task.end_reminder_mode = "elapsed"
    session = create_study_session(db, ward=other, task=task, status="active")
    db.add(StudySessionInterval(study_session_id=session.id, started_at=AT))
    db.flush()
    assert StartCueService(db).sync(ward.id, moment=AT)["notifications"] == []
    task.end_reminder_mode = "off"
    db.flush()
    assert StartCueService(db).sync(other.id, moment=AT)["notifications"] == []








def test_incremental_reminder_migration_keeps_history_unsubscribed(db):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    ward = create_ward(db)
    task = create_task(db, ward=ward, planned_minutes=20)
    ident = task.id
    db.commit()
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations/versions/20261104_34_task_end_reminder.py"
    )
    spec = importlib.util.spec_from_file_location("reminder_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        migration.upgrade()
    row = connection.execute(
        text("SELECT planned_minutes, end_reminder_mode FROM tasks WHERE id=:id"),
        {"id": ident.replace("-", "")},
    ).one()
    assert row == (20, None)
