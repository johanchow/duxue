from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from app.application.queries.planning_suggestions import DurationSuggestionQuery
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.contexts.planning.domain.time_suggestions import suggest_plan_time
from app.infrastructure.persistence.models import StudySession
from tests.support.factories import create_task, create_ward


TODAY = date(2026, 10, 22)


def _completed(db, ward, title, minutes, days_ago=1):
    task = create_task(db, ward=ward, title=title)
    task.status = "completed"
    finished = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time(), timezone.utc)
    db.add(StudySession(ward_id=ward.id, task_id=task.id, status="completed",
                        ended_at=finished, active_seconds=minutes * 60))
    db.flush()
    return task


def test_duration_suggestion_uses_three_same_ward_same_title_recent_completed_tasks(db):
    ward = create_ward(db)
    other = create_ward(db)
    for minutes in (20, 25, 30):
        _completed(db, ward, "英语 阅读", minutes)
    _completed(db, other, "英语阅读", 120)
    _completed(db, ward, "数学", 100)
    _completed(db, ward, "英语阅读", 90, days_ago=16)

    suggestion = DurationSuggestionQuery(db).for_title(
        ward_id=ward.id, title="英语阅读", plan_date=TODAY)

    assert suggestion["suggested_minutes"] == 25
    assert suggestion["sample_count"] == 3
    assert suggestion["basis"] == "同名任务近15天实际用时"


def test_duration_suggestion_requires_three_distinct_valid_tasks(db):
    ward = create_ward(db)
    task = _completed(db, ward, "数学", 20)
    db.add(StudySession(ward_id=ward.id, task_id=task.id, status="completed",
                        ended_at=datetime.now(timezone.utc), active_seconds=30 * 60))
    _completed(db, ward, "数学", 0)
    _completed(db, ward, "数学", 30, days_ago=15)
    assert DurationSuggestionQuery(db).for_title(
        ward_id=ward.id, title="数学", plan_date=TODAY) is None


def test_time_suggestion_is_soft_and_keeps_duration(db):
    early = {"assignment_id": "a", "start_at": "2026-10-22T06:30:00+08:00",
             "end_at": "2026-10-22T07:00:00+08:00", "planned_minutes": 30}
    result = suggest_plan_time(early, [early], TODAY)
    assert result["code"] == "too_early"
    assert result["suggested_start_at"].endswith("07:00:00+08:00")
    assert result["suggested_end_at"].endswith("07:30:00+08:00")

    late = {"assignment_id": "b", "start_at": "2026-10-22T21:45:00+08:00",
            "end_at": "2026-10-22T22:15:00+08:00", "planned_minutes": 30}
    result = suggest_plan_time(late, [late], TODAY)
    assert result["code"] == "too_late"
    assert result["suggested_start_at"].endswith("21:30:00+08:00")


def test_time_suggestion_does_not_propose_overlapping_move(db):
    early = {"assignment_id": "a", "start_at": "2026-10-22T06:30:00+08:00",
             "end_at": "2026-10-22T07:00:00+08:00", "planned_minutes": 30}
    busy = {"assignment_id": "b", "start_at": "2026-10-22T07:00:00+08:00",
            "end_at": "2026-10-22T07:30:00+08:00", "planned_minutes": 30}
    result = suggest_plan_time(early, [early, busy], TODAY)
    assert result["code"] == "too_early"
    assert result["suggested_start_at"] is None


def test_draft_view_exposes_only_material_duration_and_soft_time_suggestions(db):
    ward = create_ward(db)
    for minutes in (25, 30, 35):
        _completed(db, ward, "数学", minutes)
    task = create_task(db, ward=ward, title="数学", planned_minutes=10)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, TODAY, [{"assignment_id": task.id,
        "title": task.title, "planned_minutes": 10,
        "start_at": "2026-10-22T06:30:00+08:00"}])

    view = service.plan_draft_view(ward.id, draft.id)
    item = view["items"][-1]
    assert item["duration_suggestion"]["suggested_minutes"] == 30
    assert item["time_suggestion"]["code"] == "too_early"
    assert view["confirm_enabled"]  # Advice never blocks Ward's decision.


def test_missing_duration_slot_contains_history_suggestion_without_creating_task(db):
    ward = create_ward(db)
    for minutes in (20, 25, 30):
        _completed(db, ward, "英语阅读", minutes)
    service = PlanningDomainService(db)
    draft = service.apply_operations(ward.id, TODAY, [{"kind": "create",
        "title": "英语阅读"}], command_id="new-task")

    view = service.plan_draft_view(ward.id, draft.id)
    slot = view["clarification_batch"]["slots"][0]
    assert slot["field"] == "planned_minutes"
    assert slot["duration_suggestion"]["suggested_minutes"] == 25


def test_accept_duration_suggestion_updates_task_and_invalidates_old_draft_version(db):
    ward = create_ward(db)
    for minutes in (25, 30, 35):
        _completed(db, ward, "数学", minutes)
    task = create_task(db, ward=ward, title="数学", planned_minutes=10)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, TODAY, [{"assignment_id": task.id,
        "title": task.title, "planned_minutes": 10,
        "start_at": "2026-10-22T19:00:00+08:00"}])
    old_version = draft.version
    fingerprint = service.plan_draft_view(ward.id, draft.id)["items"][0]["duration_suggestion"]["fingerprint"]

    updated = service.accept_suggestion(ward.id, draft.id, old_version,
                                         kind="duration", task_id=task.id,
                                         expected_fingerprint=fingerprint)
    assert updated.version > old_version
    assert task.planned_minutes == 30
    assert service.plan_draft_view(ward.id, draft.id)["items"][0]["end_at"].endswith("19:30:00+08:00")
    with pytest.raises(HTTPException) as exc:
        service.accept_suggestion(ward.id, draft.id, old_version,
                                  kind="duration", task_id=task.id,
                                  expected_fingerprint=fingerprint)
    assert exc.value.status_code == 409


def test_accept_time_suggestion_moves_slot_without_changing_duration(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="数学", planned_minutes=30)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, TODAY, [{"assignment_id": task.id,
        "title": task.title, "planned_minutes": 30,
        "start_at": "2026-10-22T06:30:00+08:00"}])

    fingerprint = service.plan_draft_view(ward.id, draft.id)["items"][0]["time_suggestion"]["fingerprint"]
    service.accept_suggestion(ward.id, draft.id, draft.version,
                              kind="time", task_id=task.id,
                              expected_fingerprint=fingerprint)
    item = service.plan_draft_view(ward.id, draft.id)["items"][0]
    assert item["start_at"].endswith("07:00:00+08:00")
    assert item["planned_minutes"] == 30


def test_old_duration_action_rejects_changed_history_without_draft_edit(db):
    ward = create_ward(db)
    for minutes in (25, 30, 35):
        _completed(db, ward, "数学", minutes)
    task = create_task(db, ward=ward, title="数学", planned_minutes=10)
    service = PlanningDomainService(db)
    draft = service.save_draft(ward.id, TODAY, [{"assignment_id": task.id,
        "title": task.title, "planned_minutes": 10,
        "start_at": "2026-10-22T19:00:00+08:00"}])
    fingerprint = service.plan_draft_view(ward.id, draft.id)["items"][0]["duration_suggestion"]["fingerprint"]
    _completed(db, ward, "数学", 40)

    with pytest.raises(HTTPException) as exc:
        service.accept_suggestion(ward.id, draft.id, draft.version,
                                  kind="duration", task_id=task.id,
                                  expected_fingerprint=fingerprint)
    assert exc.value.status_code == 409
    assert task.planned_minutes == 10
