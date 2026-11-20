"""Email-addressed invitations to the same Guardian–Ward access relationship."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian
from app.api.schemas import EmailCodeRequest
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.models import (
    Guardian,
    GuardianWard,
    GuardianWardInvite,
    Ward,
    now,
)

router = APIRouter(tags=["guardian-members"])
UuidPath = Annotated[str, Path(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]


def _ward(db, ward_id):
    ward = db.query(Ward).filter_by(id=ward_id).with_for_update().one_or_none()
    if ward is None:
        raise HTTPException(404, "ward not found")
    return ward


def _relation(db, ward_id, guardian_id):
    return (
        db.query(GuardianWard)
        .filter_by(ward_id=ward_id, guardian_id=guardian_id)
        .one_or_none()
    )


def _creator(db, ward):
    if ward.owner_guardian_id is not None:
        return ward.owner_guardian_id
    # Legacy wards with ambiguous ownership require an explicit owner assignment.
    members = (
        db.query(GuardianWard.guardian_id).filter_by(ward_id=ward.id).limit(2).all()
    )
    return members[0][0] if len(members) == 1 else None


def require_ward_creator(db, guardian_id, ward_id):
    ward = _ward(db, ward_id)
    if _relation(db, ward_id, guardian_id) is None:
        raise HTTPException(404, "ward not found")
    if _creator(db, ward) != guardian_id:
        raise HTTPException(403, "only the ward creator can do this")
    return ward


def _pending(db):
    return db.query(GuardianWardInvite).filter(
        GuardianWardInvite.accepted_at.is_(None),
        GuardianWardInvite.expires_at > now(),
    )


def _invitation(row):
    return {"id": row.id, "email": row.email, "expires_at": row.expires_at}


@router.get("/guardian-members")
def overview(
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    guardian = db.get(Guardian, principal.user_id)
    wards = (
        db.query(Ward)
        .join(GuardianWard, Ward.id == GuardianWard.ward_id)
        .filter(
            GuardianWard.guardian_id == guardian.id,
        )
        .order_by(Ward.display_name)
        .all()
    )
    children = []
    for ward in wards:
        owner = _creator(db, ward)
        can_manage = owner == guardian.id
        members = (
            db.query(Guardian)
            .join(GuardianWard, Guardian.id == GuardianWard.guardian_id)
            .filter(
                GuardianWard.ward_id == ward.id,
                Guardian.id != guardian.id,
            )
            .order_by(Guardian.name)
            .all()
            if can_manage
            else []
        )
        children.append(
            {
                "id": ward.id,
                "name": ward.display_name,
                "can_manage": can_manage,
                "can_leave": owner is not None and not can_manage,
                "members": [
                    {"id": m.id, "name": m.name, "email": m.email} for m in members
                ],
                "pending": [
                    _invitation(i) for i in _pending(db).filter_by(ward_id=ward.id)
                ]
                if can_manage
                else [],
            }
        )
    incoming = []
    for invitation in _pending(db).filter_by(email=guardian.email):
        ward = db.get(Ward, invitation.ward_id)
        inviter = (
            db.get(Guardian, ward.owner_guardian_id) if ward.owner_guardian_id else None
        )
        if inviter and _relation(db, ward.id, guardian.id) is None:
            incoming.append(
                {
                    **_invitation(invitation),
                    "ward_name": ward.display_name,
                    "inviter": inviter.name,
                }
            )
    return {"wards": children, "incoming": incoming}


@router.post("/wards/{ward_id}/guardian-invites", status_code=201)
def invite(
    ward_id: UuidPath,
    body: EmailCodeRequest,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    from .identity import _email

    ward = require_ward_creator(db, principal.user_id, ward_id)
    email = _email(body.email)
    if email == db.get(Guardian, principal.user_id).email:
        raise HTTPException(422, "cannot invite yourself")
    if (
        db.query(GuardianWard.id)
        .join(Guardian)
        .filter(
            GuardianWard.ward_id == ward_id,
            Guardian.email == email,
        )
        .first()
    ):
        raise HTTPException(409, "guardian already has access")
    row = _pending(db).filter_by(ward_id=ward_id, email=email).one_or_none()
    if row is None:
        ward.owner_guardian_id = principal.user_id
        row = GuardianWardInvite(
            ward_id=ward_id, email=email, expires_at=now() + timedelta(days=1)
        )
        db.add(row)
    db.commit()
    return _invitation(row)


@router.post("/guardian-invites/{invite_id}/accept", status_code=204)
def accept(
    invite_id: UuidPath,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    email = db.get(Guardian, principal.user_id).email
    row = (
        db.query(GuardianWardInvite).filter_by(id=invite_id, email=email).one_or_none()
    )
    if row is None:
        raise HTTPException(404, "invitation not found")
    ward = _ward(db, row.ward_id)
    row = (
        db.query(GuardianWardInvite)
        .filter_by(id=invite_id, email=email)
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "invitation not found")
    if row.accepted_at is not None:
        return
    if _pending(db).filter_by(id=invite_id).first() is None:
        raise HTTPException(410, "invitation expired")
    if _relation(db, ward.id, principal.user_id) is None:
        db.add(GuardianWard(ward_id=ward.id, guardian_id=principal.user_id))
    row.accepted_at = now()
    db.commit()


@router.delete("/wards/{ward_id}/guardian-invites/{invite_id}", status_code=204)
def cancel(
    ward_id: UuidPath,
    invite_id: UuidPath,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    require_ward_creator(db, principal.user_id, ward_id)
    db.query(GuardianWardInvite).filter_by(
        id=invite_id,
        ward_id=ward_id,
        accepted_at=None,
    ).delete()
    db.commit()


def _remove(db, ward_id, guardian_id):
    guardian = db.get(Guardian, guardian_id)
    if guardian is not None:
        db.query(GuardianWardInvite).filter_by(
            ward_id=ward_id,
            email=guardian.email,
            accepted_at=None,
        ).delete()
    db.query(GuardianWard).filter_by(ward_id=ward_id, guardian_id=guardian_id).delete()
    db.commit()


@router.delete("/wards/{ward_id}/guardian-members/me", status_code=204)
def leave(
    ward_id: UuidPath,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    ward = _ward(db, ward_id)
    if _relation(db, ward_id, principal.user_id) is None:
        return
    owner = _creator(db, ward)
    if owner is None or owner == principal.user_id:
        raise HTTPException(403, "only a co-guardian can leave")
    _remove(db, ward_id, principal.user_id)


@router.delete("/wards/{ward_id}/guardian-members/{guardian_id}", status_code=204)
def remove(
    ward_id: UuidPath,
    guardian_id: UuidPath,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    require_ward_creator(db, principal.user_id, ward_id)
    if guardian_id == principal.user_id:
        raise HTTPException(403, "cannot remove the ward creator")
    _remove(db, ward_id, guardian_id)
