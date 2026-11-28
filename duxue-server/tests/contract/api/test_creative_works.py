from uuid import uuid4

from app.agent_specs.creative_work import Story
from app.application.commands import creative_works
from app.infrastructure.ai.intent_classifier import parse_intent_payload
from app.infrastructure.persistence.models import OutboxEvent
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360"><circle cx="170" cy="100" r="60" fill="gold"/></svg>'


def story(*texts):
    return Story.model_validate(
        {
            "title": "看月亮",
            "pages": [
                {"text": t, "illustration": {"kind": "svg", "alt": "月亮", "svg": SVG}}
                for t in texts
            ],
        }
    )


def test_storybook_turn_versions_retries_and_saved_library(client, db, monkeypatch):
    from app.infrastructure.ai.intent_classifier import ModelIntentClassifier
    from app.application.ports.companion import IntentProposal

    monkeypatch.setattr(
        ModelIntentClassifier,
        "propose",
        lambda self, **kw: IntentProposal(
            intent="tutoring", teaching_policy="standard", creative_work=True
        ),
    )
    monkeypatch.setattr(
        creative_works, "generate", lambda payload: story("一条船。", "一轮月亮。")
    )

    def login():
        ward = create_ward(db)
        db.commit()
        token = create_access_token(
            user_id=ward.id, role="ward", ward_session_version=1
        )
        return {"Authorization": "Bearer " + token}

    h, other = login(), login()
    root = "/v1/creative-works"
    thread = client.post("/v1/conversations", headers=h, json={}).json()["thread_id"]
    body = {
        "content": "来做绘本",
        "thread_id": thread,
        "expected_thread_version": 0,
        "command_id": str(uuid4()),
    }
    r = client.post("/companion/turn", headers=h, json=body)
    assert r.is_success, r.text
    reply = r.json()["interaction"]
    assert reply["kind"] == "creative_work"
    assert (
        client.post("/companion/turn", headers=h, json=body).json()["interaction"]
        == reply
    )
    path = root + "/" + reply["artifact_id"]
    assert client.get(path, headers=other).status_code == 404
    assert client.get(root, headers=h).json()["items"] == []
    ref = client.get("/v1/conversations/" + thread + "/messages", headers=h).json()[
        "items"
    ][-1]
    assert ref["interaction_ref"]["artifact_id"] == reply["artifact_id"]
    initial = client.get(path, headers=h).json()
    first, unchanged = initial["pages"]
    update = {
        "action": "revise",
        "block_id": first["block_id"],
        "instruction": "小船加上帆",
        "expected_revision": 1,
        "command_id": "revise",
    }
    monkeypatch.setattr(creative_works, "generate", lambda payload: None)
    assert client.post(path + "/commands", headers=h, json=update).status_code == 422
    from app.infrastructure.ai.errors import ModelGatewayError

    def unavailable(payload):
        raise ModelGatewayError("invalid_model_candidate")

    monkeypatch.setattr(creative_works, "generate", unavailable)
    assert client.post(path + "/commands", headers=h, json=update).status_code == 503
    assert client.get(path, headers=h).json()["state_revision"] == 1
    monkeypatch.setattr(creative_works, "generate", lambda payload: story("船有帆。"))

    def command(body):
        r = client.post(path + "/commands", headers=h, json=body)
        assert r.is_success, r.text
        return r.json()

    revised = command(update)
    assert command(update) == revised
    assert revised["pages"][0]["block_id"] == first["block_id"]
    assert revised["pages"][1] == unchanged
    assert (
        db.query(OutboxEvent)
        .filter_by(event_type="CreationFootprintRecorded.v1")
        .count()
        == 0
    )
    version = revised["state_revision"]
    for op, expected in (("undo", initial), ("redo", revised), ("save", revised)):
        state = command({"command_id": op, "action": op, "expected_revision": version})
        assert state["pages"] == expected["pages"]
        version = state["state_revision"]
    after_save = command({**update, "command_id": "next", "expected_revision": version})
    assert after_save["version"] == 3
    assert client.delete("/v1/conversations/" + thread, headers=h).is_success
    assert (
        client.get(root, headers=h).json()["items"][0]["artifact_id"]
        == reply["artifact_id"]
    )
    assert client.get(path, headers=h).json()["saved"]
    assert (
        db.query(OutboxEvent)
        .filter_by(event_type="CreationFootprintRecorded.v1")
        .count()
        == 2
    )


def test_homework_classification_cannot_grant_creation():
    assert not parse_intent_payload(
        '{"intent":"tutoring","teaching_policy":"homework","creative_work":true}'
    ).creative_work


def test_focus_reminder_follows_active_sprint_into_new_thread(db):
    from types import SimpleNamespace
    from app.infrastructure.persistence.models import ConversationThread, Sprint

    ward = create_ward(db)
    a, b = (ConversationThread(ward_id=ward.id) for _ in range(2))
    db.add_all(
        [
            a,
            b,
            Sprint(ward_id=ward.id, status="active", topic="数学", target_seconds=1200),
        ]
    )
    db.flush()
    first = creative_works.focus_reminder(
        db, SimpleNamespace(ward_id=ward.id, thread_id=a.id)
    )
    second = creative_works.focus_reminder(
        db, SimpleNamespace(ward_id=ward.id, thread_id=b.id)
    )
    assert first == second and second["kind"] == "creative_focus_reminder"


def test_expiry_removes_only_temporary_story_versions(db):
    from datetime import timedelta
    from app.infrastructure.persistence.models import (
        ConversationThread,
        CreativeWork,
        CreativeWorkVersion,
        now,
    )

    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    for saved in (True, False):
        work = CreativeWork(
            ward_id=ward.id,
            source_thread_id=thread.id,
            title="月亮",
            updated_at=now() - timedelta(hours=5),
            saved=saved,
        )
        db.add(work)
        db.flush()
        db.add(CreativeWorkVersion(work_id=work.id, number=1, pages=[]))
    db.commit()
    assert creative_works.expire_temporary(db) == 1
    assert db.query(CreativeWork).one().saved
    assert db.query(CreativeWorkVersion).count() == 1


def test_independent_authorship_gate_stops_before_drawing(monkeypatch):
    from types import SimpleNamespace
    from app.agent_specs.catalog import AgentSpec
    from app.agent_specs.creative_work import GATE, workflow

    spec = AgentSpec.model_validate({**workflow(), "version": "test"})
    monkeypatch.setattr(
        creative_works, "load_catalog", lambda: SimpleNamespace(spec=lambda name: spec)
    )
    monkeypatch.setattr(creative_works.components.COMPONENTS, "get", lambda name: name)
    monkeypatch.setattr(creative_works, "build_context", lambda name, payload: payload)
    calls = []

    def judge(*, spec, user):
        calls.append(spec)
        assert user == {"instruction": "这是待交的作文"}
        return {"allow_creation": False}

    monkeypatch.setattr(creative_works.components, "invoke_json_component", judge)
    assert creative_works.generate({"instruction": "这是待交的作文"}) is None
    assert calls == [GATE]


def test_clear_revokes_temporary_story_access(client, db):
    from app.infrastructure.persistence.models import ConversationThread

    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    interaction = {"candidate": story("月亮升起来").model_dump()}
    creative_works.persist_candidate(db, thread, interaction)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    headers = {"Authorization": "Bearer " + token}
    path = "/v1/creative-works/" + interaction["artifact_id"]
    assert client.get(path, headers=headers).is_success
    assert client.post(f"/v1/conversations/{thread.id}/clear", headers=headers).is_success
    assert client.get(path, headers=headers).status_code == 404


def test_saved_work_rename_delete_and_undo_no_duplicate_outbox(client, db):
    from app.infrastructure.persistence.models import ConversationThread

    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    interaction = {"candidate": story("第一页", "第二页").model_dump()}
    creative_works.persist_candidate(db, thread, interaction)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    headers = {"Authorization": "Bearer " + token}
    path = "/v1/creative-works/" + interaction["artifact_id"]

    # Save emits 1 footprint event
    saved = client.post(
        path + "/commands",
        headers=headers,
        json={"action": "save", "expected_revision": 1, "command_id": "save-1"},
    )
    assert saved.is_success
    assert db.query(OutboxEvent).filter_by(event_type="CreationFootprintRecorded.v1").count() == 1

    # Rename works on saved work
    renamed = client.patch(path, headers=headers, json={"title": "我的月亮船"})
    assert renamed.is_success and renamed.json()["title"] == "我的月亮船"

    # Idempotent delete on work and conversation
    assert client.delete(path, headers=headers).status_code == 204
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert client.delete(f"/v1/conversations/{thread.id}", headers=headers).status_code == 204
    assert client.delete(f"/v1/conversations/{thread.id}", headers=headers).status_code == 204


def test_focus_reminder_only_triggers_for_active_sprint(db):
    from types import SimpleNamespace
    from app.infrastructure.persistence.models import (
        ConversationThread,
        StudySession,
        TutoringProblem,
        TutoringSession,
    )

    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    study = StudySession(ward_id=ward.id, status="active")
    db.add_all([thread, study])
    db.flush()
    sess = TutoringSession(ward_id=ward.id, study_session_id=study.id, status="active")
    db.add(sess)
    db.flush()
    db.add(TutoringProblem(tutoring_session_id=sess.id, status="open", summary="1+1"))
    db.flush()
    assert creative_works.focus_reminder(db, SimpleNamespace(ward_id=ward.id, thread_id=thread.id)) is None
