"""Capture identity and immutable evidence. No HTTP, ORM, or external clocks."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class CaptureConflict(ValueError):
    pass


@dataclass(frozen=True)
class CameraRegistration:
    device_id: str
    gateway_id: str
    camera_id: str
    ward_id: str
    revision: int = 1
    enabled: bool = True
    erased: bool = False

    def assert_assignment(self, ward_id: str, revision: int | None = None) -> None:
        if self.ward_id != ward_id or (
            revision is not None and self.revision != revision
        ):
            raise CaptureConflict("camera assignment cannot change")


@dataclass(frozen=True)
class Evidence:
    gateway_id: str
    frame_id: str
    camera_id: str
    ward_id: str
    revision: int
    captured_at: datetime
    sha256: str
    size_bytes: int

    def validate_window(self, current: datetime) -> None:
        if self.captured_at.tzinfo is None or not -timedelta(
            minutes=5
        ) <= current - self.captured_at <= timedelta(hours=12):
            raise ValueError("capture time outside allowed window")

    def object_key(self) -> str:
        return f"{self.ward_id}/{self.captured_at.date().isoformat()}/{self.frame_id}.jpg"


@dataclass(frozen=True)
class AcceptedFrame:
    id: str
    evidence: Evidence
    device_id: str
    oss_key: str

    def assert_same(self, evidence: Evidence, key: str) -> None:
        if self.evidence != evidence or self.oss_key != key:
            raise CaptureConflict("frame identity already used for different evidence")


class CameraRegistrationRepository(Protocol):
    def ward_exists(self, ward_id: str) -> bool: ...
    def camera(self, gateway_id: str, camera_id: str) -> CameraRegistration | None: ...
    def add_camera(
        self, gateway_id: str, camera_id: str, ward_id: str
    ) -> CameraRegistration: ...


class AcceptedFrameRepository(Protocol):
    def accepted(self, evidence: Evidence) -> AcceptedFrame | None: ...
    def add_frame(
        self, camera: CameraRegistration, evidence: Evidence, key: str
    ) -> AcceptedFrame: ...
