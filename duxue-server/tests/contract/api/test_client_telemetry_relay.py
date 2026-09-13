from __future__ import annotations

from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward


def _payload():
    return {
        "events": [{
            "signal": "span", "name": "app.http", "duration_ms": 12,
            "attributes": {"result": "success", "route": "/wards/:id/report"},
            "trace_id": "a" * 32, "span_id": "b" * 16,
        }]
    }


def test_mobile_telemetry_relay_requires_existing_short_lived_login(client):
    response = client.post("/telemetry/client-events", json=_payload())
    assert response.status_code == 401


def test_mobile_telemetry_relay_accepts_ward_context_without_exporting_identity(client, db, monkeypatch):
    ward = create_ward(db)
    db.commit()
    monkeypatch.setattr("app.api.v1.system.relay_client_telemetry", lambda events: len(events))
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)

    response = client.post(
        "/telemetry/client-events", json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 1}


def test_mobile_telemetry_relay_rejects_private_content_even_when_authenticated(client, db):
    ward = create_ward(db)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    payload = _payload()
    payload["events"][0]["attributes"] = {"content": "child private text"}

    response = client.post(
        "/telemetry/client-events", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
