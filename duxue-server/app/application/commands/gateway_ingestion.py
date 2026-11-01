"""Gateway commands coordinate local transactions through injected ports."""

from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.contexts.ingestion.domain.gateway import (
    AcceptedFrameRepository,
    CameraRegistration,
    CameraRegistrationRepository,
    CaptureConflict,
    Evidence,
)


class GatewayError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


@dataclass(frozen=True)
class GatewayPrincipal:
    gateway_id: str
    allowed_ward_ids: frozenset[str]

    def authorize(self, ward_id: str):
        if ward_id not in self.allowed_ward_ids:
            raise GatewayError(403, "WARD_FORBIDDEN")


class CaptureRepository(Protocol):
    """Unit of work plus technical stores; aggregate ports remain distinct."""

    cameras: CameraRegistrationRepository
    frames: AcceptedFrameRepository

    def audit(self, event_type: str, aggregate_id: str, ward_id: str) -> None: ...
    def publish_fact(self, **fact) -> None: ...
    def transaction(self, key: str) -> AbstractContextManager: ...
    def reserve(
        self,
        camera: CameraRegistration,
        evidence: Evidence,
        key: str,
        *,
        require_existing: bool = False,
    ) -> None: ...
    def delete_reservation(self, gateway_id: str, frame_id: str) -> None: ...
    def heartbeat(
        self,
        gateway_id: str,
        boot_id: str,
        sequence: int,
        cameras: list[dict],
        current: datetime,
    ) -> None: ...


class CaptureStorage(Protocol):
    def upload_url(
        self, key: str, base_url: str, content_type: str, *, immutable: bool = False
    ) -> tuple[str, int, dict]: ...
    def read_limited(self, key: str, maximum: int) -> bytes: ...


class GatewayCommands:
    def __init__(self, repository: CaptureRepository, storage: CaptureStorage):
        self.repository, self.storage = repository, storage
        self.cameras, self.frames = repository.cameras, repository.frames

    def _camera(
        self,
        actor: GatewayPrincipal,
        camera_id: str,
        ward_id: str,
        revision: int | None = None,
    ):
        actor.authorize(ward_id)
        if not self.cameras.ward_exists(ward_id):
            raise GatewayError(403, "WARD_DELETED")
        camera = self.cameras.camera(actor.gateway_id, camera_id)
        if camera is None:
            raise GatewayError(409, "CAMERA_NOT_REGISTERED")
        if camera.erased:
            raise GatewayError(403, "WARD_DATA_ERASED")
        camera.assert_assignment(ward_id, revision)
        if not camera.enabled:
            raise GatewayError(403, "CAMERA_DISABLED")
        return camera

    def register(self, actor: GatewayPrincipal, camera_id: str, ward_id: str):
        actor.authorize(ward_id)
        with self.repository.transaction(f"camera:{actor.gateway_id}:{camera_id}"):
            if not self.cameras.ward_exists(ward_id):
                raise GatewayError(403, "WARD_DELETED")
            camera = self.cameras.camera(actor.gateway_id, camera_id)
            if camera is not None:
                if camera.erased:
                    raise GatewayError(403, "WARD_DATA_ERASED")
                camera.assert_assignment(ward_id)
                if not camera.enabled:
                    raise GatewayError(403, "CAMERA_DISABLED")
                return camera, False
            camera = self.cameras.add_camera(actor.gateway_id, camera_id, ward_id)
            self.repository.audit("CameraRegistered", camera.device_id, ward_id)
            return camera, True

    def reserve(
        self,
        actor: GatewayPrincipal,
        evidence: Evidence,
        current: datetime,
        base_url: str,
    ):
        actor.authorize(evidence.ward_id)
        try:
            evidence.validate_window(current)
        except ValueError:
            raise GatewayError(422, "CAPTURE_TIME_INVALID") from None
        key = evidence.object_key()
        with self.repository.transaction(
            f"frame:{actor.gateway_id}:{evidence.frame_id}"
        ):
            camera = self._camera(
                actor, evidence.camera_id, evidence.ward_id, evidence.revision
            )
            existing = self.frames.accepted(evidence)
            if existing:
                existing.assert_same(evidence, key)
            else:
                self.repository.reserve(camera, evidence, key)
        url, expires, headers = self.storage.upload_url(
            key, base_url, "image/jpeg", immutable=True
        )
        return {
            "oss_key": key,
            "upload_url": url,
            "expires_at": datetime.fromtimestamp(expires, current.tzinfo),
            "headers": headers,
        }

    def accept(
        self, actor: GatewayPrincipal, evidence: Evidence, key: str, current: datetime
    ):
        # Resolve repeats before the time window: an already accepted frame can be
        # acknowledged after twelve hours without creating or rewriting evidence.
        actor.authorize(evidence.ward_id)
        with self.repository.transaction(
            f"frame:{actor.gateway_id}:{evidence.frame_id}"
        ):
            camera = self._camera(
                actor, evidence.camera_id, evidence.ward_id, evidence.revision
            )
            existing = self.frames.accepted(evidence)
            if existing:
                existing.assert_same(evidence, key)
                return existing, False
        try:
            evidence.validate_window(current)
        except ValueError:
            raise GatewayError(422, "CAPTURE_TIME_INVALID") from None
        if key != evidence.object_key():
            raise CaptureConflict("object key differs from evidence identity")
        # IO outside write transaction. Immutable PUT prevents a TOCTOU overwrite.
        try:
            data = self.storage.read_limited(key, 1024 * 1024)
        except FileNotFoundError:
            raise GatewayError(422, "OBJECT_NOT_READY") from None
        if (
            len(data) != evidence.size_bytes
            or hashlib.sha256(data).hexdigest() != evidence.sha256
            or not (data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"))
        ):
            raise GatewayError(409, "OBJECT_MISMATCH")
        with self.repository.transaction(
            f"frame:{actor.gateway_id}:{evidence.frame_id}"
        ):
            camera = self._camera(
                actor, evidence.camera_id, evidence.ward_id, evidence.revision
            )
            existing = self.frames.accepted(evidence)
            if existing:
                existing.assert_same(evidence, key)
                return existing, False
            self.repository.reserve(camera, evidence, key, require_existing=True)
            frame = self.frames.add_frame(camera, evidence, key)
            self.repository.audit("FrameAccepted", frame.id, evidence.ward_id)
            self.repository.publish_fact(
                ward_id=evidence.ward_id,
                event_type="camera_frame.captured",
                source_type="frame",
                source_id=frame.id,
                occurred_at=evidence.captured_at,
                source="cam",
                payload={"device_id": camera.device_id},
            )
            self.repository.delete_reservation(actor.gateway_id, evidence.frame_id)
            return frame, True

    def heartbeat(
        self,
        actor: GatewayPrincipal,
        boot_id: str,
        sequence: int,
        cameras: list[dict],
        current: datetime,
    ):
        with self.repository.transaction(f"health:{actor.gateway_id}"):
            for status in cameras:
                camera = self.cameras.camera(actor.gateway_id, status["camera_id"])
                if not camera:
                    raise GatewayError(409, "CAMERA_NOT_REGISTERED")
                self._camera(actor, camera.camera_id, camera.ward_id)
            self.repository.heartbeat(
                actor.gateway_id, boot_id, sequence, cameras, current
            )


class CleanupGatewayUploads:
    """Claim an expired orphan before external deletion; failed deletes stay resumable."""

    def __init__(self, repository, storage):
        self.repository, self.storage = repository, storage
        self.cameras, self.frames = repository.cameras, repository.frames

    def run(self, current):
        from datetime import timedelta

        removed = 0
        cursor = None
        while batch := self.repository.orphan_candidates(
            current - timedelta(hours=24), after=cursor, limit=500
        ):
            for gateway_id, frame_id, key in batch:
                with self.repository.transaction(f"frame:{gateway_id}:{frame_id}"):
                    claimed = self.repository.mark_orphan(gateway_id, frame_id)
                if claimed:
                    self.storage.delete(key)
                    with self.repository.transaction(f"frame:{gateway_id}:{frame_id}"):
                        self.repository.delete_reservation(gateway_id, frame_id)
                    removed += 1
            cursor = batch[-1][:2]
        return removed
