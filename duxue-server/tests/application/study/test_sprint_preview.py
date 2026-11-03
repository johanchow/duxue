import json
from unittest.mock import patch

from app.agent_specs.results import completed
from app.infrastructure.persistence.models import Sprint, StudySession, Task
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian, create_ward


def _headers(ward):
    return {
        "Authorization": "Bearer "
        + create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    }


def _candidate(**values):
    return patch(
        "app.application.queries.sprint_preview.components.invoke_agent_component",
        return_value=completed(
            {
                "topic": None,
                "target_minutes": None,
                "cancelled": False,
                "needs_clarification": False,
                **values,
            }
        ),
    )


def test_voice_preview_never_starts_or_creates_work_and_topic_is_optional(client, db):
    ward = create_ward(db)
    db.commit()
    with _candidate(target_minutes=20) as model:
        result = client.post(
            "/sprints/preview",
            headers=_headers(ward),
            json={"content": "先专心二十分钟"},
        )
    assert result.status_code == 200
    assert result.json() == {
        "status": "ready",
        "topic": "专注挑战",
        "target_minutes": 20,
        "message": "专注挑战 · 20分钟",
    }
    assert json.loads(model.call_args.kwargs["user"]) == {
        "utterance": "先专心二十分钟",
        "previous": {},
    }
    assert (
        db.query(Sprint).count()
        == db.query(Task).count()
        == db.query(StudySession).count()
        == 0
    )


def test_missing_duration_keeps_current_spoken_topic_for_followup(client, db):
    ward = create_ward(db)
    db.commit()
    with _candidate(topic="数学"):
        result = client.post(
            "/sprints/preview", headers=_headers(ward), json={"content": "写数学"}
        )
    assert result.json() == {
        "status": "needs_duration",
        "topic": "数学",
        "target_minutes": None,
        "message": "想试多久？",
    }
    with _candidate(topic="数学", target_minutes=15) as model:
        result = client.post(
            "/sprints/preview",
            headers=_headers(ward),
            json={
                "content": "十五分钟",
                "previous": {"topic": "数学", "target_minutes": None},
            },
        )
    assert result.json()["target_minutes"] == 15
    assert json.loads(model.call_args.kwargs["user"])["previous"]["topic"] == "数学"


def test_preview_clarifies_uncertainty_without_guardian_authority(client, db):
    ward = create_ward(db)
    guardian = create_guardian(db)
    db.commit()
    with _candidate(needs_clarification=True):
        result = client.post(
            "/sprints/preview", headers=_headers(ward), json={"content": "明天几点？"}
        )
    assert result.json()["status"] == "clarify"
    assert result.json()["target_minutes"] is None
    headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=guardian.id, role="guardian")
    }
    assert (
        client.post(
            "/sprints/preview", headers=headers, json={"content": "二十分钟"}
        ).status_code
        == 403
    )


def test_spoken_cancellation_closes_setup_without_starting(client, db):
    ward = create_ward(db)
    db.commit()
    with _candidate(cancelled=True):
        result = client.post(
            "/sprints/preview", headers=_headers(ward), json={"content": "先不用挑战了"}
        )
    assert result.json()["status"] == "cancelled"
    assert db.query(Sprint).count() == 0


def test_model_unavailable_does_not_supply_a_default_duration(client, db):
    from app.agent_specs.results import AgentResult

    ward = create_ward(db)
    db.commit()
    with patch(
        "app.application.queries.sprint_preview.components.invoke_agent_component",
        return_value=AgentResult(status="failed", error_code="model_transport_error"),
    ):
        response = client.post(
            "/sprints/preview", headers=_headers(ward), json={"content": "写数学"}
        )
    assert response.status_code == 502
    assert db.query(Sprint).count() == 0
