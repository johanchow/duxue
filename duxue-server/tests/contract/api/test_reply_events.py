import json
from types import SimpleNamespace

from fastapi import HTTPException

from app.agent_specs.runtime import notify_node_started
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward


def test_ward_turn_streams_allowlisted_stages_and_preserves_json_callers(client, db, monkeypatch):
    ward = create_ward(db, display_name="进度", session_version=1)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    headers = {"Authorization": f"Bearer {token}"}
    calls = []

    def handle(self, **kwargs):
        calls.append(kwargs["ward_id"])
        for node in ("companion.route", "tutoring.attempt", "内部草稿", "tutoring.exit_gate"):
            notify_node_started(node)
        if kwargs["content"] == "过期":
            raise HTTPException(409, "交互已过期")
        return SimpleNamespace(model_dump=lambda: {"interaction": {"content": "已校验答复"}})

    monkeypatch.setattr("app.api.v1.companion.CompanionCoordinator.handle", handle)
    for stream in (False, True):
        response = client.post(
            "/companion/turn", json={"content": "继续"},
            headers={**headers, "Accept": "text/event-stream"} if stream else headers,
        )
        assert response.status_code == 200
        reply = {"interaction": {"content": "已校验答复"}}
        if stream:
            assert response.headers["content-type"].startswith("text/event-stream")
            events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line]
            assert events == [
                {"type": "stage", "value": "route"},
                {"type": "stage", "value": "draft"},
                {"type": "stage", "value": "check"},
                {"type": "result", "value": reply},
            ]
        else:
            assert response.json() == reply

    failed = client.post(
        "/companion/turn", json={"content": "过期"},
        headers={**headers, "Accept": "text/event-stream"},
    )
    last = failed.text.strip().splitlines()[-1]
    assert json.loads(last.removeprefix("data: ")) == {
        "type": "error", "value": {"status": 409, "detail": "交互已过期"},
    }
    assert calls == [ward.id] * 3
