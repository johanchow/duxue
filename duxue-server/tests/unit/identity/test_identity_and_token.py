from __future__ import annotations

import time
import pytest
from fastapi import HTTPException

from app.dependencies import current_ward
from app.models import WardCredential
from app.security import (
    create_access_token,
    decode_access_token,
    hash_secret,
    verify_secret,
)
from app.services import make_invite_code
from tests.support.factories import create_ward


def test_password_hashing_and_verification():
    """PBKDF2 密码加盐哈希及校验。"""
    raw = "MySecurePassword2026!"
    hashed = hash_secret(raw)
    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_secret(raw, hashed)
    assert not verify_secret("WrongPassword", hashed)


def test_jwt_signature_tampering_rejected():
    """任何对 Token Header、Payload 或 Signature 的篡改都必须导致解析失败。"""
    token = create_access_token(user_id="user-1", role="guardian")
    parts = token.split(".")
    # 篡改 payload 的最后一个字符
    tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

    with pytest.raises(ValueError):
        decode_access_token(tampered_token)


def test_ward_session_version_invalidation(db):
    """当学生重新扫码绑定导致 session_version 递增时，旧 Token 必须被立即使失效。"""
    ward = create_ward(db, session_version=1)
    db.commit()

    # 使用版本 1 签发 Token
    valid_token = create_access_token(
        user_id=ward.id,
        role="ward",
        ward_session_version=1,
    )

    # 递增版本（模拟重新绑定）
    cred = db.get(WardCredential, ward.id)
    cred.session_version = 2
    db.commit()

    # 旧 Token 请求 current_ward 应拒绝 401
    with pytest.raises(HTTPException) as exc:
        current_ward(authorization=f"Bearer {valid_token}", db=db)
    assert exc.value.status_code == 401
    assert "session has been replaced" in exc.value.detail


def test_make_invite_code_length_and_charset(db):
    """6位邀请码使用排除易混淆字符的字母表生成。"""
    code = make_invite_code(db)
    assert len(code) == 6
    assert code.isalnum()
    # 排除容易混淆的 0, 1, I, O
    for char in ["0", "1", "I", "O"]:
        assert char not in code
