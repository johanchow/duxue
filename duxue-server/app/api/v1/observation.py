from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.deps import (
    Principal,
    current_guardian,
    current_guardian_or_ward,
    current_ward,
)
from app.application.commands.behavior_observation import lock
from app.application.commands.help_offers import HelpOfferCommands
from app.application.commands.legacy_services import owned_ward
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.models import (
    Device,
    ObservationSettings,
    ReflectionReportRecord,
    ReflectionReportVersion,
    SupportChannel,
    now,
)

router = APIRouter(tags=["observation"])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    camera_id: UUID | None = None
    report_enabled: bool = True
    deadline: str = "21:30"
    observation_ranges: list[tuple[datetime, datetime]] | None = None

    @field_validator("observation_ranges")
    @classmethod
    def valid_ranges(cls, value):
        if value is None:
            return None
        if len(value) > 100:
            raise ValueError("too many observation ranges")
        for start, end in value:
            if start.tzinfo is None or end.tzinfo is None or start >= end:
                raise ValueError("timezone-aware nonempty range required")
        ordered = sorted(value)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("ranges overlap")
        return ordered

    @field_validator("deadline")
    @classmethod
    def valid_time(cls, value):
        from datetime import time

        parsed = time.fromisoformat(value)
        if parsed.tzinfo or len(value) != 5:
            raise ValueError("HH:MM required")
        return value


@router.put("/wards/{ward_id}/observation-settings")
def configure(
    ward_id: str,
    body: SettingsInput,
    principal: Principal = Depends(current_guardian),
    db: Session = Depends(get_db),
):
    owned_ward(db, principal.user_id, ward_id)
    lock(db, f"observation-ward:{ward_id}")
    camera = str(body.camera_id) if body.camera_id else None
    if (
        camera
        and not db.query(Device)
        .filter_by(
            id=camera, ward_id=ward_id, gateway_enabled=True, gateway_erased=False
        )
        .first()
    ):
        raise HTTPException(404, "camera not found")
    if body.enabled and not camera:
        raise HTTPException(422, "camera required")
    row = db.get(ObservationSettings, ward_id)
    if row is None:
        row = ObservationSettings(ward_id=ward_id, generation=0)
        db.add(row)
    if row.enabled != body.enabled or row.camera_id != camera:
        row.generation += 1
        row.report_next_date = None
    if row.deadline != body.deadline or row.report_enabled != body.report_enabled:
        row.report_next_date = None
    row.observation_ranges = (
        [[a.isoformat(), b.isoformat()] for a, b in body.observation_ranges]
        if body.observation_ranges is not None
        else None
    )
    row.enabled, row.camera_id, row.report_enabled, row.deadline = (
        body.enabled,
        camera,
        body.report_enabled,
        body.deadline,
    )
    db.commit()
    return {
        "enabled": row.enabled,
        "mode": row.mode,
        "report_enabled": row.report_enabled,
        "deadline": row.deadline,
    }


class ChannelInput(BaseModel):
    enabled: bool
    handsfree: bool = False


@router.post("/companion/support-channels")
def channel(
    body: ChannelInput,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    ward_id = principal.user_id
    lock(db, f"observation-ward:{ward_id}")
    setting = db.get(ObservationSettings, ward_id)
    if not setting or not setting.enabled:
        raise HTTPException(409, "observation is not enabled")
    # Shadow remains controlled by deployment/validated rollout; Ward opt-in
    # opens a channel but cannot bypass the shadow quality gate.
    row = db.query(SupportChannel).filter_by(ward_id=ward_id).one_or_none()
    if row is None:
        row = SupportChannel(ward_id=ward_id)
        db.add(row)
    from app.bootstrap.settings import settings

    setting.mode = (
        "enabled"
        if settings.observation_live_invitations_enabled and body.enabled
        else "shadow"
    )
    row.enabled, row.handsfree = body.enabled, body.handsfree
    row.expires_at = now() + timedelta(seconds=45)
    db.commit()
    return {"id": row.id, "expires_at": row.expires_at, "mode": setting.mode}


@router.get("/companion/support-channels/{channel_id}/offer")
def offer(
    channel_id: str,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    value = HelpOfferCommands(db).present(principal.user_id, channel_id)
    db.commit()
    return {"offer": value}


class ReceiptInput(BaseModel):
    offer_id: UUID
    receipt_id: UUID
    medium: Literal["card_rendered", "speech_completed", "speech_suppressed"]
    presented_at: datetime
    expected_version: int


@router.post("/companion/support-channels/{channel_id}/receipts")
def receipt(
    channel_id: str,
    body: ReceiptInput,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    result = HelpOfferCommands(db).receipt(
        principal.user_id,
        channel_id,
        offer_id=str(body.offer_id),
        receipt_id=str(body.receipt_id),
        medium=body.medium,
        presented_at=body.presented_at,
        expected_version=body.expected_version,
    )
    db.commit()
    return result


class RespondInput(BaseModel):
    action: Literal["accept_help", "decline_help"]
    expected_version: int
    command_id: UUID


@router.post("/study/help-offers/{offer_id}/responses")
def respond(
    offer_id: str,
    body: RespondInput,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    result = HelpOfferCommands(db).respond(
        principal.user_id,
        offer_id,
        body.action,
        body.expected_version,
        str(body.command_id),
    )
    db.commit()
    return result


@router.get("/evaluation/evening-reports")
def report(
    ward_id: str,
    day: date = Query(alias="date"),
    version: int | None = Query(None, ge=1),
    principal: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    if principal.role == "ward":
        if principal.user_id != ward_id:
            raise HTTPException(404, "ward not found")
    else:
        owned_ward(db, principal.user_id, ward_id)
    row = (
        db.query(ReflectionReportRecord)
        .filter_by(ward_id=ward_id, report_date=day)
        .one_or_none()
    )
    if not row:
        from fastapi.responses import JSONResponse

        setting = db.get(ObservationSettings, ward_id)
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending",
                "deadline": setting.deadline if setting else None,
            },
        )
    item = db.get(ReflectionReportVersion, (row.id, version or row.current_version))
    if item is None:
        raise HTTPException(404, "report version not found")
    return {
        "report_id": row.id,
        "version": item.version,
        "published_at": item.published_at,
        **item.content,
    }


@router.get("/wards/{ward_id}/observation-settings")
def get_settings(
    ward_id: str,
    principal: Principal = Depends(current_guardian),
    db: Session = Depends(get_db),
):
    owned_ward(db, principal.user_id, ward_id)
    row = db.get(ObservationSettings, ward_id)
    return {
        "enabled": bool(row and row.enabled),
        "camera_id": row.camera_id if row else None,
        "report_enabled": bool(row and row.report_enabled),
        "deadline": row.deadline if row else "21:30",
    }


@router.get("/evaluation/report-inbox")
def report_inbox(
    principal: Principal = Depends(current_guardian),
    db: Session = Depends(get_db),
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    from app.infrastructure.persistence.models import GuardianReportInbox, GuardianWard

    query = (
        db.query(GuardianReportInbox, ReflectionReportRecord)
        .join(
            ReflectionReportRecord,
            ReflectionReportRecord.id == GuardianReportInbox.report_id,
        )
        .join(
            GuardianWard,
            (GuardianWard.ward_id == ReflectionReportRecord.ward_id)
            & (GuardianWard.guardian_id == principal.user_id),
        )
        .filter(GuardianReportInbox.guardian_id == principal.user_id)
    )
    if cursor:
        try:
            UUID(cursor)
        except ValueError:
            raise HTTPException(422, "invalid cursor")
        query = query.filter(ReflectionReportRecord.id > cursor)
    rows = query.order_by(ReflectionReportRecord.id).limit(limit).all()
    return {
        "items": [
            {
                "report_id": report.id,
                "ward_id": report.ward_id,
                "local_date": report.report_date,
                "latest_version": inbox.version,
            }
            for inbox, report in rows
        ],
        "next_cursor": rows[-1][1].id if len(rows) == limit else None,
    }
