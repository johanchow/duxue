from __future__ import annotations

import pytest

from app.security import create_access_token
from tests.support.factories import create_guardian, create_ward


def test_missing_token_returns_401(client):
    """缺少 Bearer Token 返回 401。"""
    response = client.get("/ward/profile")
    assert response.status_code == 401
    assert "missing bearer token" in response.text


def test_invalid_token_returns_401(client):
    """伪造或无效的 Bearer Token 返回 401。"""
    response = client.get("/ward/profile", headers={"Authorization": "Bearer fake.token.here"})
    assert response.status_code == 401
    assert "invalid or expired" in response.text


def test_guardian_accessing_unbound_ward_returns_404(client, db):
    """监护人访问未经绑定的其他学生资源返回 404。"""
    guardian = create_guardian(db, name="王家长", email="wang_acl@example.com")
    ward_other = create_ward(db, display_name="别人家孩子")  # 未绑定到 guardian
    db.commit()

    token = create_access_token(user_id=guardian.id, role="guardian")

    response = client.post(
        f"/wards/{ward_other.id}/login-invite",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_ward_profile_contract_and_guardian_field(client, db):
    """学生获取个人资料返回 200，并展示其绑定的监护人姓名。"""
    guardian = create_guardian(db, name="李妈妈", email="li_acl@example.com")
    ward = create_ward(db, guardian=guardian, display_name="小李同学", session_version=1)
    db.commit()

    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)

    response = client.get(
        "/ward/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "小李同学"
    assert len(data["guardians"]) == 1
    assert data["guardians"][0]["name"] == "李妈妈"
