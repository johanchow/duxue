from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.deps import Principal
from app.api.schemas import EmailCodeRequest, WardCreate, WardPatch
from app.api.v1 import guardian_members as members
from app.api.v1.identity import create_ward, delete_ward_data, list_wards, patch_ward
from app.infrastructure.persistence.models import GuardianWardInvite, now
from tests.support.factories import create_guardian


@pytest.fixture
def household(db):
    creator, recipient, outsider = (create_guardian(db) for _ in range(3))
    owner, guest, stranger = (
        Principal(g.id, "guardian") for g in (creator, recipient, outsider)
    )
    ward = create_ward(
        WardCreate(display_name="小宇", grade_stage="primary"), owner, db
    )
    return ward.id, owner, guest, stranger, recipient.email


def test_accept_same_daily_permissions_and_remove(db, household):
    ward_id, owner, guest, stranger, email = household
    invitation = members.invite(
        ward_id, EmailCodeRequest(email=email.upper()), owner, db
    )
    invite_id = invitation["id"]
    assert members.overview(guest, db)["incoming"][0]["ward_name"] == "小宇"
    assert list_wards(guest, db) == []
    with pytest.raises(HTTPException) as wrong_account:
        members.accept(invite_id, stranger, db)
    assert wrong_account.value.status_code == 404

    members.accept(invite_id, guest, db)
    members.accept(invite_id, guest, db)
    assert len(list_wards(guest, db)) == 1
    patch_ward(ward_id, WardPatch(display_name="小海", grade_stage="middle"), guest, db)
    assert list_wards(owner, db)[0].display_name == "小海"
    assert members.overview(guest, db)["wards"][0]["can_leave"]
    with pytest.raises(HTTPException) as management_denied:
        members.invite(ward_id, EmailCodeRequest(email=email), guest, db)
    assert management_denied.value.status_code == 403
    with pytest.raises(HTTPException) as deletion_denied:
        delete_ward_data(ward_id, guest, db)
    assert deletion_denied.value.status_code == 403

    members.remove(ward_id, guest.user_id, owner, db)
    members.accept(invite_id, guest, db)
    assert list_wards(guest, db) == []
    with pytest.raises(HTTPException) as access_denied:
        patch_ward(ward_id, WardPatch(display_name="无权限"), guest, db)
    assert access_denied.value.status_code == 404


def test_cancel_expire_and_leave(db, household):
    ward_id, owner, guest, _, email = household
    body = EmailCodeRequest(email=email)
    invite_id = members.invite(ward_id, body, owner, db)["id"]
    assert members.invite(ward_id, body, owner, db)["id"] == invite_id
    members.cancel(ward_id, invite_id, owner, db)
    with pytest.raises(HTTPException) as cancelled:
        members.accept(invite_id, guest, db)
    assert cancelled.value.status_code == 404

    invite_id = members.invite(ward_id, body, owner, db)["id"]
    db.get(GuardianWardInvite, invite_id).expires_at = now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as expired:
        members.accept(invite_id, guest, db)
    assert expired.value.status_code == 410
    assert members.overview(guest, db)["incoming"] == []

    invite_id = members.invite(ward_id, body, owner, db)["id"]
    members.accept(invite_id, guest, db)
    members.leave(ward_id, guest, db)
    assert list_wards(guest, db) == []
    with pytest.raises(HTTPException) as owner_leave:
        members.leave(ward_id, owner, db)
    assert owner_leave.value.status_code == 403
