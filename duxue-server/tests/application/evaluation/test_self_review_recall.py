from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.application.commands.self_reviews import confirm_self_review
from app.application.queries.review_draft import propose_review_aspects
from app.application.queries.review_prompt import review_invitation
from app.application.queries.self_reviews import get_recent_self_reviews
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.persistence.models import (
    SelfReviewAspect, SelfReviewVersion, StudySession, TutoringProblem, TutoringSession,
)
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian, create_task, create_ward


DAY = date(2026, 10, 23)


def _aspect(statement="数学最后一道我弄懂了", quote="最后一道我弄懂了", task_ref=None):
    return {"dimension": "understanding", "statement": statement,
            "source_quote": quote, "task_ref": task_ref}


def test_confirm_revision_recall_only_current_version_and_source(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward)
    first = confirm_self_review(
        db, ward_id=ward.id, review_date=DAY,
        raw_expression="数学最后一道我弄懂了", aspects=[_aspect(task_ref=task.id)],
        expected_version=0,
    )
    db.commit()
    assert first.version == 1
    second = confirm_self_review(
        db, ward_id=ward.id, review_date=DAY,
        raw_expression="数学最后一道又有疑问，下次先画图", aspects=[
            {"dimension": "understanding", "statement": "最后一道仍有疑问",
             "source_quote": "最后一道又有疑问", "task_ref": task.id},
            {"dimension": "next_intent", "statement": "下次先画图",
             "source_quote": "下次先画图", "task_ref": task.id},
        ], expected_version=1,
    )
    db.commit()
    assert second.version == 2
    assert db.query(SelfReviewVersion).filter_by(review_id=first.id).count() == 2
    assert db.query(SelfReviewAspect).filter_by(review_id=first.id).count() == 3
    kwargs = dict(actor_id=ward.id, actor_role="ward", ward_id=ward.id,
                  end_date=DAY, task_ref=task.id)
    rows = get_recent_self_reviews(db, use_case="tutoring", **kwargs)
    assert [row["statement"] for row in rows] == ["最后一道仍有疑问", "下次先画图"]
    assert all(row["version"] == 2 and row["source"] == "ward_self_report" for row in rows)
    assert [row["dimension"] for row in get_recent_self_reviews(db, use_case="planning", **kwargs)] == ["next_intent"]


def test_review_rejects_unquoted_aspect_foreign_task_and_stale_revision(db):
    ward = create_ward(db)
    other = create_ward(db)
    task = create_task(db, ward=other)
    with pytest.raises(HTTPException) as bad_quote:
        confirm_self_review(db, ward_id=ward.id, review_date=DAY,
                            raw_expression="今天我画了图", aspects=[_aspect()], expected_version=0)
    assert bad_quote.value.status_code == 422
    with pytest.raises(HTTPException) as foreign_task:
        confirm_self_review(db, ward_id=ward.id, review_date=DAY,
                            raw_expression="最后一道我弄懂了", aspects=[_aspect(task_ref=task.id)],
                            expected_version=0)
    assert foreign_task.value.status_code == 422
    confirm_self_review(db, ward_id=ward.id, review_date=DAY,
                        raw_expression="今天我画了图", aspects=[], expected_version=0)
    db.commit()
    with pytest.raises(HTTPException) as stale:
        confirm_self_review(db, ward_id=ward.id, review_date=DAY,
                            raw_expression="今天我画了图", aspects=[], expected_version=0)
    assert stale.value.status_code == 409


def test_direct_recall_is_ward_only_and_budgeted(db):
    ward = create_ward(db)
    other = create_ward(db)
    confirm_self_review(db, ward_id=ward.id, review_date=DAY,
                        raw_expression="我画图之后理解了，明天先读题", aspects=[
                            {"dimension": "strategy", "statement": "画图帮助理解", "source_quote": "画图之后理解了"},
                            {"dimension": "next_intent", "statement": "明天先读题", "source_quote": "明天先读题"},
                        ], expected_version=0)
    db.commit()
    kwargs = dict(ward_id=ward.id, use_case="ward_history", end_date=DAY)
    assert len(get_recent_self_reviews(db, actor_id=ward.id, actor_role="ward", item_budget=1, **kwargs)) == 1
    for actor_id, role in [(other.id, "ward"), (ward.id, "guardian")]:
        with pytest.raises(HTTPException) as denied:
            get_recent_self_reviews(db, actor_id=actor_id, actor_role=role, **kwargs)
        assert denied.value.status_code == 403


def test_draft_discards_unsupported_or_unquoted_model_claims():
    with patch("app.application.queries.review_draft.components.invoke_json_component") as model:
        model.return_value = {"aspects": [
            {"dimension": "understanding", "statement": "我懂了", "source_quote": "我懂了"},
            {"dimension": "affect", "statement": "我很开心", "source_quote": "我很开心"},
            {"dimension": "made_up", "statement": "我懂了", "source_quote": "我懂了"},
        ]}
        assert propose_review_aspects("我懂了") == [
            {"dimension": "understanding", "statement": "我懂了", "source_quote": "我懂了"}]
        model.side_effect = ModelGatewayError("offline")
        assert propose_review_aspects("我懂了") == []


def test_invitation_uses_today_question_and_elapsed_time_without_inventing_cause(db):
    ward = create_ward(db)
    task = create_task(db, ward=ward, title="数学练习", planned_minutes=20)
    session = StudySession(ward_id=ward.id, task_id=task.id,
                           started_at=datetime(2026, 10, 23, 4, tzinfo=timezone.utc),
                           active_seconds=1800)
    db.add(session)
    db.flush()
    tutor = TutoringSession(ward_id=ward.id, study_session_id=session.id)
    db.add(tutor)
    db.flush()
    db.add(TutoringProblem(tutoring_session_id=tutor.id, summary="分数约分"))
    db.commit()
    result = review_invitation(db, ward_id=ward.id, review_date=DAY)
    assert "分数约分" in result["prompt"]
    assert "数学练习" in result["prompt"]
    assert "原因是什么" in result["prompt"]
    assert "不专心" not in result["prompt"]
    assert result["question_count"] == result["overrun_count"] == 1


def test_review_http_confirm_read_and_ward_isolation(client, db):
    ward = create_ward(db)
    other = create_ward(db)
    guardian = create_guardian(db)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    other_token = create_access_token(user_id=other.id, role="ward", ward_session_version=1)
    guardian_token = create_access_token(user_id=guardian.id, role="guardian")
    path = f"/wards/{ward.id}/reviews/{DAY.isoformat()}"
    headers = {"Authorization": f"Bearer {token}"}
    confirmation = client.put(path + "/confirm", headers=headers, json={
        "raw_expression": "我画图之后理解了", "expected_version": 0,
        "aspects": [{"dimension": "strategy", "statement": "画图帮助理解",
                     "source_quote": "画图之后理解了"}],
    })
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["version"] == 1
    assert client.get(path, headers=headers).json()["aspects"][0]["dimension"] == "strategy"
    assert len(client.get(f"/wards/{ward.id}/reviews/recent?end_date={DAY.isoformat()}",
                          headers=headers).json()["items"]) == 1
    assert client.get(path, headers={"Authorization": f"Bearer {other_token}"}).status_code == 403
    assert client.get(path, headers={"Authorization": f"Bearer {guardian_token}"}).status_code == 403
    assert client.put(path + "/confirm", headers=headers, json={
        "raw_expression": "我画图之后理解了", "expected_version": 0, "aspects": [],
    }).status_code == 409
