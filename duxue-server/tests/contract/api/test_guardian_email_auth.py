from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from app.infrastructure.persistence.models import EmailAuthChallenge, Guardian, now


def _send(client, mail, email="parent@example.com"):
    response = client.post("/auth/email-code/send", json={"email": email})
    assert response.status_code == 202, response.text
    assert "code" not in response.text.lower()
    assert len(mail.call_args_list) > 0
    return mail.call_args.kwargs["code"]


def test_registration_and_login_require_single_use_email_code(client, db):
    with patch("app.api.v1.identity.send_email_code") as mail:
        code = _send(client, mail)
        assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "code": "000000"}).status_code == 400
        registered = client.post("/auth/register", json={"name": "Parent", "email": "PARENT@example.com", "code": code})
        assert registered.status_code == 201, registered.text
        assert registered.json()["access_token"]
        assert db.query(Guardian).count() == 1
        assert client.post("/auth/login", json={"email": "parent@example.com", "code": code}).status_code == 400

        db.query(EmailAuthChallenge).order_by(EmailAuthChallenge.created_at.desc()).first().created_at = now() - timedelta(seconds=61)
        db.commit()
        next_code = _send(client, mail)
        logged_in = client.post("/auth/login", json={"email": "parent@example.com", "code": next_code})
        assert logged_in.status_code == 200, logged_in.text
        assert logged_in.json()["refresh_token"]
        assert client.post("/auth/login", json={"email": "parent@example.com", "code": next_code}).status_code == 400


def test_unknown_guardian_login_returns_404_and_code_can_register(client, db):
    with patch("app.api.v1.identity.send_email_code") as mail:
        code = _send(client, mail, "new@example.com")
        login = client.post("/auth/login", json={"email": "new@example.com", "code": code})
        assert login.status_code == 404
        assert login.json() == {"detail": "account not found"}
        assert db.query(Guardian).count() == 0

        registered = client.post("/auth/register", json={"name": "Parent", "email": "new@example.com", "code": code})
        assert registered.status_code == 201, registered.text


def test_expired_code_and_password_cannot_authenticate(client, db):
    with patch("app.api.v1.identity.send_email_code") as mail:
        code = _send(client, mail)
        challenge = db.query(EmailAuthChallenge).one()
        challenge.expires_at = now() - timedelta(seconds=1)
        db.commit()
        assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "code": code}).status_code == 400
        assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "password": "password123"}).status_code == 422
        assert client.post("/auth/login", json={"email": "parent@example.com", "password": "password123"}).status_code == 422
        assert db.query(Guardian).count() == 0


def test_send_failure_does_not_leave_usable_code(client, db):
    with patch("app.api.v1.identity.send_email_code", side_effect=OSError("smtp unavailable")):
        response = client.post("/auth/email-code/send", json={"email": "parent@example.com"})
        assert response.status_code == 503
        assert "smtp unavailable" not in response.text
        assert db.query(EmailAuthChallenge).count() == 0


def test_resend_invalidates_old_code_and_limits_attempts(client, db):
    with patch("app.api.v1.identity.send_email_code") as mail:
        old_code = _send(client, mail)
        assert client.post("/auth/email-code/send", json={"email": "parent@example.com"}).status_code == 429
        db.query(EmailAuthChallenge).one().created_at = now() - timedelta(seconds=61)
        db.commit()
        new_code = _send(client, mail)
        assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "code": old_code}).status_code == 400
        wrong_code = next(code for code in ("111111", "222222", "333333") if code not in {old_code, new_code})
        for _ in range(4):
            assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "code": wrong_code}).status_code == 400
        assert client.post("/auth/register", json={"name": "Parent", "email": "parent@example.com", "code": new_code}).status_code == 400
        assert db.query(Guardian).count() == 0


def test_hourly_email_limit_applies_after_cooldown(client, db):
    with patch("app.api.v1.identity.send_email_code") as mail:
        for _ in range(5):
            _send(client, mail)
            db.query(EmailAuthChallenge).order_by(EmailAuthChallenge.created_at.desc()).first().created_at = now() - timedelta(seconds=61)
            db.commit()
        rejected = client.post("/auth/email-code/send", json={"email": "parent@example.com"})
        assert rejected.status_code == 429
        assert mail.call_count == 5


def test_verification_failures_are_limited_across_challenges(client):
    for _ in range(20):
        response = client.post("/auth/login", json={"email": "unknown@example.com", "code": "123456"})
        assert response.status_code == 400
    assert client.post("/auth/login", json={"email": "unknown@example.com", "code": "123456"}).status_code == 429
