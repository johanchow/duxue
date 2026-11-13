from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.infrastructure.ai.behavior_observation import ObservationVision
from app.infrastructure.persistence.evidence_repository import record_accepted_evidence
from app.infrastructure.persistence.models import ObservationSettings
from tests.unit.behavior.test_evidence_journal import make_frame


def test_adapter_sends_real_images_and_never_foreign_ward(db, db_engine):
    frame = make_frame(db)
    frame.oss_key = "test.jpg"
    record_accepted_evidence(db, frame, 3)
    db.add(
        ObservationSettings(
            ward_id=frame.ward_id, camera_id=frame.device_id, enabled=True
        )
    )
    db.commit()
    payload = {
        "ward_id": frame.ward_id,
        "camera_id": frame.device_id,
        "assignment_revision": 3,
        "frames": [{"id": frame.id, "at": frame.captured_at.isoformat()}],
    }
    adapter = ObservationVision(sessionmaker(bind=db_engine))
    with patch(
        "app.infrastructure.ai.behavior_observation.storage.read_bytes",
        return_value=b"image",
    ):
        parts = adapter.prepare(payload, limit=8)
    assert parts[-1]["type"] == "image_url"
    assert parts[-1]["image_url"]["url"] == "data:image/jpeg;base64,aW1hZ2U="
    with pytest.raises(PermissionError):
        adapter.prepare({**payload, "assignment_revision": 4}, limit=8)


def test_image_budget_rejects_duplicates_before_loading():
    with pytest.raises(ValueError):
        ObservationVision().prepare({"frames": [{"id": "one"}, {"id": "one"}]}, limit=8)


def test_adapter_rejects_fabricated_capture_time(db, db_engine):
    frame = make_frame(db)
    frame.oss_key = "test.jpg"
    record_accepted_evidence(db, frame, 3)
    db.add(
        ObservationSettings(
            ward_id=frame.ward_id, camera_id=frame.device_id, enabled=True
        )
    )
    db.commit()
    with pytest.raises(PermissionError, match="timestamp"):
        ObservationVision(sessionmaker(bind=db_engine)).prepare(
            {
                "ward_id": frame.ward_id,
                "camera_id": frame.device_id,
                "assignment_revision": 3,
                "frames": [{"id": frame.id, "at": "2000-01-01T00:00:00+00:00"}],
            },
            limit=8,
        )
