from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Device, Guardian
from .security import decode_access_token, token_hash


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization.split(" ", 1)[1]


def current_guardian(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Principal:
    try:
        claims = decode_access_token(_bearer(authorization))
    except ValueError:
        raise HTTPException(401, "invalid or expired access token")
    if db.get(Guardian, claims["sub"]) is None:
        raise HTTPException(401, "guardian no longer exists")
    return Principal(claims["sub"], claims["tenant_id"], claims["role"])


def current_device(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> Device:
    digest = token_hash(_bearer(authorization))
    device = db.query(Device).filter(Device.device_token_hash == digest).one_or_none()
    if device is None:
        raise HTTPException(401, "invalid device token")
    return device
