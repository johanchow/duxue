"""Capture-only HTTP adapter. Commands own authorization and transactions."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.commands.gateway_ingestion import (
    GatewayCommands,
    GatewayError,
    GatewayPrincipal,
)
from app.bootstrap.gateway import gateway_commands as commands
from app.bootstrap.settings import settings
from app.contexts.ingestion.domain.gateway import Evidence
from app.infrastructure.observability.telemetry import record_frame
from app.infrastructure.security.gateway import authenticate

router = APIRouter(prefix="/gateway", tags=["gateway-ingestion"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CameraInput(Strict):
    camera_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    ward_id: UUID


class EvidenceInput(CameraInput):
    assignment_revision: int = Field(ge=1)
    frame_id: UUID
    captured_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=4, le=1024 * 1024)
    content_type: Literal["image/jpeg"] = "image/jpeg"

    @field_validator("captured_at")
    @classmethod
    def utc_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("UTC timestamp required")
        return value.astimezone(timezone.utc)

    def evidence(self, actor):
        return Evidence(
            actor.gateway_id,
            str(self.frame_id),
            self.camera_id,
            str(self.ward_id),
            self.assignment_revision,
            self.captured_at,
            self.sha256,
            self.size_bytes,
        )


class CommitInput(EvidenceInput):
    oss_key: str = Field(max_length=500)


class CameraHealth(Strict):
    camera_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    last_capture_at: datetime | None = None
    last_submit_at: datetime | None = None
    queue_frames: int = Field(ge=0)
    queue_bytes: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    last_error_code: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z_]+$"
    )


class HeartbeatInput(Strict):
    boot_id: UUID
    sequence: int = Field(ge=1, le=2**31 - 1)
    cameras: list[CameraHealth] = Field(max_length=64)


def principal(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer ") or len(authorization) > 512:
        raise GatewayError(401, "GATEWAY_UNAUTHORIZED")
    actor = authenticate(authorization[7:])
    if actor is None:
        raise GatewayError(401, "GATEWAY_UNAUTHORIZED")
    return actor


@router.post("/cameras")
def register(
    body: CameraInput,
    actor: Annotated[GatewayPrincipal, Depends(principal)],
    service: Annotated[GatewayCommands, Depends(commands)],
):
    camera, created = service.register(actor, body.camera_id, str(body.ward_id))
    return JSONResponse(
        status_code=201 if created else 200,
        content={
            "gateway_id": camera.gateway_id,
            "device_id": camera.device_id,
            "camera_id": camera.camera_id,
            "ward_id": camera.ward_id,
            "assignment_revision": camera.revision,
        },
    )


@router.post("/frames/upload-url")
def upload_url(
    body: EvidenceInput,
    request: Request,
    actor: Annotated[GatewayPrincipal, Depends(principal)],
    service: Annotated[GatewayCommands, Depends(commands)],
):
    base = (
        str(request.base_url)
        if settings.storage_backend == "local"
        else settings.public_base_url
    )
    return service.reserve(
        actor, body.evidence(actor), datetime.now(timezone.utc), base
    )


@router.post("/frames")
def accept(
    body: CommitInput,
    actor: Annotated[GatewayPrincipal, Depends(principal)],
    service: Annotated[GatewayCommands, Depends(commands)],
):
    frame, created = service.accept(
        actor, body.evidence(actor), body.oss_key, datetime.now(timezone.utc)
    )
    record_frame(result="accepted" if created else "duplicate")
    return JSONResponse(
        status_code=201 if created else 200,
        content={
            "id": frame.id,
            "frame_id": frame.evidence.frame_id,
            "captured_at": frame.evidence.captured_at.isoformat(),
            "duplicate": not created,
        },
    )


@router.post("/heartbeat")
def heartbeat(
    body: HeartbeatInput,
    actor: Annotated[GatewayPrincipal, Depends(principal)],
    service: Annotated[GatewayCommands, Depends(commands)],
):
    if len({c.camera_id for c in body.cameras}) != len(body.cameras):
        raise GatewayError(422, "DUPLICATE_CAMERA")
    current = datetime.now(timezone.utc)
    service.heartbeat(
        actor,
        str(body.boot_id),
        body.sequence,
        [c.model_dump(mode="json") for c in body.cameras],
        current,
    )
    return {"server_time": current}
