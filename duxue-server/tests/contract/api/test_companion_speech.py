from unittest.mock import AsyncMock

from app.infrastructure.persistence.models import (
    AgentRun,
    CompanionCommand,
    CompanionMessage,
    ConversationThread,
    uid,
)
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward


def test_read_aloud_supports_visible_agent_replies_and_hides_legacy_invitations(
    client, db, monkeypatch
):
    ward = create_ward(db, display_name="甲", session_version=1)
    other = create_ward(db, display_name="乙", session_version=1)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    run = AgentRun(
        thread_id=thread.id, ward_id=ward.id, agent_type="tutoring", run_ref="lesson"
    )
    command = CompanionCommand(
        id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="sample"
    )
    db.add_all([run, command])
    db.flush()

    def message(role, version, text):
        return CompanionMessage(
            ward_id=ward.id,
            thread_id=thread.id,
            run_id=run.id,
            command_id=command.id,
            thread_version=version,
            author_type=role,
            content=text,
        )

    question, reply = (
        message("ward", 1, "不会"),
        message("companion", 2, "先看已知条件。"),
    )
    db.add_all([question, reply])
    db.commit()
    synth = AsyncMock(return_value=b"mp3")
    monkeypatch.setattr("app.api.v1.companion.tutor_audio", synth)

    def headers(user):
        token = create_access_token(
            user_id=user.id, role="ward", ward_session_version=1
        )
        return {"Authorization": f"Bearer {token}"}

    url = f"/companion/messages/{reply.id}/speech"
    assert client.get(url, headers=headers(other)).status_code == 404
    assert (
        client.get(
            f"/companion/messages/{question.id}/speech", headers=headers(ward)
        ).status_code
        == 404
    )
    result = client.get(url, headers=headers(ward))
    assert result.content == b"mp3"
    assert result.headers["content-type"] == "audio/mpeg"
    synth.assert_awaited_once_with("先看已知条件。")
    legacy = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id,
                              payload_digest="support.invitation.v1")
    plan_command = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="planning")
    db.add_all([legacy, plan_command])
    db.flush()
    reminder = message("companion", 3, "要不要回到刚才这一步？")
    reminder.command_id = legacy.id
    reminder.run_id = None
    planning = message("companion", 4, "作业已经记下了。")
    planning.run_id = None
    planning.command_id = plan_command.id
    db.add_all([reminder, planning])
    db.commit()
    history = client.get("/companion/threads/current/messages", headers=headers(ward)).json()
    assert [m["id"] for m in history["messages"]] == [question.id, reply.id, planning.id]
    assert client.get(f"/companion/messages/{reminder.id}/speech", headers=headers(ward)).status_code == 404
    assert client.get(f"/companion/messages/{planning.id}/speech", headers=headers(ward)).content == b"mp3"
    ward.history_generation += 1
    db.commit()
    assert client.get(url, headers=headers(ward)).status_code == 404
