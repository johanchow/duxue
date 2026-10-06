from datetime import datetime, timezone

from app.application.commands.start_cue import StartCueService
from app.contexts.planning.domain.scheduling import local_plan_date
from app.contexts.study.domain.start_cue import SceneRead, StartCueError
from app.infrastructure.persistence.models import LearningEvent, StudySession, StudySessionInterval
from tests.support.factories import create_daily_schedule, create_guardian, create_study_session, create_task, create_ward

AT = datetime(2026, 10, 6, 11, 10, tzinfo=timezone.utc)  # 19:10 Asia/Shanghai
AT_NEXT = datetime(2026, 10, 6, 11, 41, tzinfo=timezone.utc)  # 19:41 Asia/Shanghai


def _schedule(db, ward):
    schedule = create_daily_schedule(db, ward=ward, status="confirmed", version=1)
    schedule.schedule_date = local_plan_date(AT)
    db.flush()
    return schedule


def test_due_task_without_a_camera_presents_one_card(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", planned_minutes=40, status="scheduled", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": math.id,
        "planned_minutes": 40,
        "start_at": "2026-10-06T19:00:00",
        "end_at": "2026-10-06T19:40:00",
    }]
    db.flush()

    view = StartCueService(db).sync(ward.id, moment=AT)
    assert view["status"] == "presented"
    assert "没看到书桌" in view["text"]
    assert view["actions"][0]["command"] == "start_due_task"
    assert view["actions"][-1]["command"] == "snooze_once"
    assert db.query(LearningEvent).filter_by(event_type="start_cue.presented").count() == 0


def test_previous_task_still_running_offers_continue_or_switch(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", planned_minutes=40, status="scheduled", schedule_id=schedule.id, position=0)
    english = create_task(db, ward=ward, title="英语", planned_minutes=20, status="scheduled", schedule_id=schedule.id, position=1)
    create_study_session(db, ward=ward, task=math, status="active")
    schedule.items = [
        {"assignment_id": math.id, "start_at": "2026-10-06T19:00:00", "end_at": "2026-10-06T19:40:00", "planned_minutes": 40},
        {"assignment_id": english.id, "start_at": "2026-10-06T19:40:00", "end_at": "2026-10-06T20:00:00", "planned_minutes": 20},
    ]
    db.flush()

    view = StartCueService(db).sync(ward.id, moment=AT_NEXT)
    assert view["status"] == "presented"
    commands = [action["command"] for action in view["actions"][:2]]
    assert commands == ["continue_current", "pause_current_and_start_due"]
    assert "继续数学" in view["text"]
    assert "没看清书桌" in view["text"]


def test_away_does_not_present_a_card(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    english = create_task(db, ward=ward, title="英语", status="scheduled", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": english.id,
        "start_at": "2026-10-06T19:40:00",
        "end_at": "2026-10-06T20:00:00",
        "planned_minutes": 20,
    }]
    db.flush()

    view = StartCueService(db).sync(ward.id, moment=AT_NEXT, scene=SceneRead("away"))
    assert view["status"] == "held"
    assert "text" not in view


def test_accept_switch_pauses_the_current_session_and_starts_the_due_task(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", status="scheduled", schedule_id=schedule.id)
    english = create_task(db, ward=ward, title="英语", status="scheduled", schedule_id=schedule.id)
    current = create_study_session(db, ward=ward, task=math, status="active")
    db.add(StudySessionInterval(study_session_id=current.id))
    schedule.items = [
        {"assignment_id": math.id, "start_at": "2026-10-06T19:00:00", "end_at": "2026-10-06T19:40:00", "planned_minutes": 40},
        {"assignment_id": english.id, "start_at": "2026-10-06T19:40:00", "end_at": "2026-10-06T20:00:00", "planned_minutes": 20},
    ]
    db.flush()
    service = StartCueService(db)
    view = service.sync(ward.id, moment=AT_NEXT)
    result = service.act(ward.id, view["id"], "pause_current_and_start_due", view["version"])
    assert result["status"] == "accepted"
    assert db.get(StudySession, current.id).status == "paused"
    started = db.query(StudySession).filter_by(task_id=english.id, status="active").one()
    assert started.ward_id == ward.id


def test_second_snooze_is_rejected(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", status="scheduled", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": math.id,
        "start_at": "2026-10-06T19:00:00",
        "end_at": "2026-10-06T19:40:00",
        "planned_minutes": 40,
    }]
    db.flush()
    service = StartCueService(db)
    view = service.sync(ward.id, moment=AT)
    service.act(ward.id, view["id"], "snooze_once", view["version"])
    try:
        service.act(ward.id, view["id"], "snooze_once", view["version"] + 1)
    except StartCueError as error:
        assert error.code == "not_presented"
    else:
        raise AssertionError("expected not_presented")


def test_earlier_unstarted_task_stays_on_the_same_card(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", status="scheduled", schedule_id=schedule.id)
    english = create_task(db, ward=ward, title="英语", status="scheduled", schedule_id=schedule.id)
    schedule.items = [
        {"assignment_id": math.id, "start_at": "2026-10-06T19:00:00", "end_at": "2026-10-06T19:40:00", "planned_minutes": 40},
        {"assignment_id": english.id, "start_at": "2026-10-06T19:40:00", "end_at": "2026-10-06T20:00:00", "planned_minutes": 20},
    ]
    db.flush()
    view = StartCueService(db).sync(ward.id, moment=AT_NEXT)
    assert [task["title"] for task in view["tasks"]] == ["数学", "英语"]
    assert view["tasks"][-1]["due"] is True
    assert "数学也还没开始" in view["text"]


def test_a_new_schedule_version_expires_the_open_cue(db):
    ward = create_ward(db, guardian=create_guardian(db))
    schedule = _schedule(db, ward)
    math = create_task(db, ward=ward, title="数学", status="scheduled", schedule_id=schedule.id)
    schedule.items = [{
        "assignment_id": math.id,
        "start_at": "2026-10-06T19:00:00",
        "end_at": "2026-10-06T19:40:00",
        "planned_minutes": 40,
    }]
    db.flush()
    service = StartCueService(db)
    first = service.sync(ward.id, moment=AT)
    schedule.version = 2
    db.flush()
    second = service.sync(ward.id, moment=AT)
    assert first["id"] != second["id"]
    assert second["status"] == "presented"
