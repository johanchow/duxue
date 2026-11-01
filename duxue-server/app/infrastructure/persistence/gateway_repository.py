"""SQLAlchemy adapter for capture command ports. Owns no HTTP contracts."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict
from datetime import timezone

from sqlalchemy import text

from app.application.commands.gateway_ingestion import GatewayError
from app.contexts.ingestion.domain.gateway import (
    AcceptedFrame,
    CameraRegistration,
    CaptureConflict,
    Evidence,
)
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.persistence.models import (
    CaptureAudit,
    Device,
    Frame,
    GatewayHealth,
    GatewayUploadReservation,
    Ward,
    now,
)


def utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def fingerprint(evidence):
    body = asdict(evidence)
    body["captured_at"] = evidence.captured_at.astimezone(timezone.utc).isoformat()
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class SqlCaptureRepository:
    def __init__(self, db):
        self.db = db
        self.cameras = self
        self.frames = self

    @contextmanager
    def transaction(self, key):
        try:
            if self.db.bind.dialect.name == "postgresql":
                lock = int.from_bytes(
                    hashlib.sha256(key.encode()).digest()[:8], "big", signed=True
                )
                self.db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock}
                )
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def ward_exists(self, ward_id):
        return self.db.get(Ward, ward_id) is not None

    def camera(self, gateway_id, camera_id):
        row = (
            self.db.query(Device)
            .filter_by(gateway_id=gateway_id, camera_id=camera_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if row is None:
            return None
        return CameraRegistration(
            row.id,
            row.gateway_id,
            row.camera_id,
            row.ward_id,
            row.assignment_revision,
            row.gateway_enabled,
            row.gateway_erased,
        )

    def add_camera(self, gateway_id, camera_id, ward_id):
        row = Device(
            gateway_id=gateway_id,
            camera_id=camera_id,
            ward_id=ward_id,
            device_type="ip_camera",
            assignment_revision=1,
            gateway_enabled=True,
        )
        self.db.add(row)
        self.db.flush()
        return CameraRegistration(row.id, gateway_id, camera_id, ward_id)

    def reserve(self, camera, evidence, key, *, require_existing=False):
        row = self.db.get(
            GatewayUploadReservation, (evidence.gateway_id, evidence.frame_id)
        )
        digest = fingerprint(evidence)
        if row:
            if row.purging:
                raise GatewayError(409, "UPLOAD_EXPIRED")
            if (
                row.device_id != camera.device_id
                or row.fingerprint != digest
                or row.oss_key != key
            ):
                raise CaptureConflict("reservation identity conflict")
            return
        if require_existing:
            raise GatewayError(409, "UPLOAD_NOT_RESERVED")
        self.db.add(
            GatewayUploadReservation(
                gateway_id=evidence.gateway_id,
                frame_id=evidence.frame_id,
                device_id=camera.device_id,
                oss_key=key,
                fingerprint=digest,
            )
        )
        self.db.flush()

    def accepted(self, evidence):
        row = (
            self.db.query(Frame)
            .filter_by(
                gateway_id=evidence.gateway_id, gateway_frame_id=evidence.frame_id
            )
            .one_or_none()
        )
        if row is None:
            return None
        device = self.db.get(Device, row.device_id)
        original = Evidence(
            row.gateway_id,
            row.gateway_frame_id,
            device.camera_id,
            row.ward_id,
            device.assignment_revision,
            utc(row.captured_at),
            row.sha256,
            row.size_bytes,
        )
        return AcceptedFrame(row.id, original, row.device_id, row.oss_key)

    def add_frame(self, camera, evidence, key):
        from datetime import timedelta

        from app.bootstrap.settings import settings

        row = Frame(
            device_id=camera.device_id,
            ward_id=evidence.ward_id,
            gateway_id=evidence.gateway_id,
            gateway_frame_id=evidence.frame_id,
            captured_at=evidence.captured_at,
            oss_key=key,
            sha256=evidence.sha256,
            size_bytes=evidence.size_bytes,
            purge_after=now() + timedelta(days=settings.frame_retention_days),
        )
        self.db.add(row)
        self.db.flush()
        return AcceptedFrame(row.id, evidence, camera.device_id, key)

    def heartbeat(self, gateway_id, boot_id, sequence, cameras, current):
        row = self.db.get(GatewayHealth, gateway_id)
        if row:
            if boot_id in row.retired_boots or (
                boot_id == row.boot_id and sequence <= row.sequence
            ):
                raise GatewayError(409, "STALE_HEARTBEAT")
            if boot_id != row.boot_id:
                row.retired_boots = [*row.retired_boots, row.boot_id]
                # Bound remembered boots. Deployments normally send one per process.
                if len(row.retired_boots) > 1024:
                    raise GatewayError(409, "HEALTH_HISTORY_EXHAUSTED")
            row.boot_id, row.sequence, row.cameras, row.received_at = (
                boot_id,
                sequence,
                cameras,
                current,
            )
        else:
            self.db.add(
                GatewayHealth(
                    gateway_id=gateway_id,
                    boot_id=boot_id,
                    sequence=sequence,
                    cameras=cameras,
                    received_at=current,
                )
            )
        for status in cameras:
            device = (
                self.db.query(Device)
                .filter_by(gateway_id=gateway_id, camera_id=status["camera_id"])
                .one()
            )
            device.last_heartbeat_at = current

    def orphan_candidates(self, cutoff):
        return [
            (r.gateway_id, r.frame_id, r.oss_key)
            for r in self.db.query(GatewayUploadReservation)
            .filter(GatewayUploadReservation.created_at < cutoff)
            .all()
        ]

    def mark_orphan(self, gateway_id, frame_id):
        row = self.db.get(GatewayUploadReservation, (gateway_id, frame_id))
        if row is None:
            return False
        existing = (
            self.db.query(Frame.id)
            .filter_by(gateway_id=gateway_id, gateway_frame_id=frame_id)
            .first()
        )
        if existing:
            return False
        row.purging = True
        return True

    def delete_reservation(self, gateway_id, frame_id):
        self.db.query(GatewayUploadReservation).filter_by(
            gateway_id=gateway_id, frame_id=frame_id, purging=True
        ).delete(synchronize_session=False)

    def audit(self, event_type, aggregate_id, ward_id):
        self.db.add(
            CaptureAudit(
                ward_id=ward_id, aggregate_id=aggregate_id, event_type=event_type
            )
        )

    def publish_fact(self, **fact):
        publish_learning_fact(self.db, **fact)
