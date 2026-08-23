from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Device, Guardian, Ward, WardCredential
from .security import decode_access_token, token_hash


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization.split(" ", 1)[1]


def guardian_principal_for_token(token: str, db: Session) -> Principal:
    try:
        claims = decode_access_token(token)
    except ValueError:
        raise HTTPException(401, "invalid or expired access token")
    guardian = db.get(Guardian, claims.get("sub"))
    if guardian is None or claims.get("role") not in {"admin", "guardian"}:
        raise HTTPException(401, "guardian login required")
    return Principal(guardian.id, guardian.role)


def current_guardian(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    return guardian_principal_for_token(_bearer(authorization), db)

def current_ward(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    try:
        claims = decode_access_token(_bearer(authorization))
    except ValueError:
        raise HTTPException(401, "invalid or expired access token")
    credential = db.get(WardCredential, claims.get("sub"))
    if claims.get("role") != "ward" or db.get(Ward, claims.get("sub")) is None:
        raise HTTPException(403, "ward login required")
    if credential is None or claims.get("ward_session_version", 0) != credential.session_version:
        raise HTTPException(401, "ward session has been replaced")
    return Principal(claims["sub"], "ward")


def current_guardian_or_ward(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    token = _bearer(authorization)
    try:
        claims = decode_access_token(token)
    except ValueError:
        raise HTTPException(401, "invalid or expired access token")
    if claims.get("role") == "ward" and db.get(Ward, claims.get("sub")) is not None:
        credential = db.get(WardCredential, claims["sub"])
        if credential is None or claims.get("ward_session_version", 0) != credential.session_version:
            raise HTTPException(401, "ward session has been replaced")
        return Principal(claims["sub"], "ward")
    return guardian_principal_for_token(token, db)


def current_device(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Device:
    digest = token_hash(_bearer(authorization))
    device = db.query(Device).filter(Device.device_token_hash == digest).one_or_none()
    if device is None:
        raise HTTPException(401, "invalid device token")
    return device
