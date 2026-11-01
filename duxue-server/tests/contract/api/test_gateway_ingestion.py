"""Gateway authentication and two-step, immutable evidence contract."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.infrastructure.persistence.models import Device, Frame, OutboxEvent, Ward


@pytest.fixture
def gateway(db, monkeypatch):
    ward = Ward(id=str(uuid4()), display_name="gateway child", grade_stage="primary")
    db.add(ward)
    db.commit()
    token = "gateway-test-token-that-is-never-logged"
    monkeypatch.setattr(
        "app.infrastructure.security.gateway.credential_config",
        lambda: json.dumps(
            [
                {
                    "gateway_id": "home-01",
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "allowed_ward_ids": [ward.id],
                    "enabled": True,
                }
            ]
        ),
    )
    return ward.id, {"Authorization": f"Bearer {token}"}


def test_gateway_register_without_binding_code(client, gateway):
    ward, headers = gateway
    body = {"camera_id": "camera-01", "ward_id": ward}
    result = client.post("/gateway/cameras", headers=headers, json=body)
    assert result.status_code == 201, result.text
    assert result.json()["gateway_id"] == "home-01"
    repeated = client.post(
        "/gateway/cameras",
        headers={
            "Authorization": headers["Authorization"].replace("Bearer ", "bearer ", 1)
        },
        json=body,
    )
    assert repeated.status_code == 200
    assert repeated.json() == result.json()
    assert client.post("/gateway/cameras", json=body).status_code == 401
    assert (
        client.post(
            "/gateway/cameras", headers=headers, json={**body, "ward_id": str(uuid4())}
        ).status_code
        == 403
    )


def test_gateway_upload_retries_keep_key_and_single_fact(client, gateway, db):
    ward, headers = gateway
    registration = client.post(
        "/gateway/cameras",
        headers=headers,
        json={"camera_id": "camera-01", "ward_id": ward},
    ).json()
    image = b"\xff\xd8jpeg-test\xff\xd9"
    body = {
        "camera_id": "camera-01",
        "ward_id": ward,
        "assignment_revision": registration["assignment_revision"],
        "frame_id": str(uuid4()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(image).hexdigest(),
        "size_bytes": len(image),
        "content_type": "image/jpeg",
    }
    reservation = client.post("/gateway/frames/upload-url", headers=headers, json=body)
    assert reservation.status_code == 200, reservation.text
    target = reservation.json()
    captured = datetime.fromisoformat(body["captured_at"])
    assert target["oss_key"] == f"{ward}/{captured.date().isoformat()}/{body['frame_id']}.jpg"
    again = client.post("/gateway/frames/upload-url", headers=headers, json=body)
    assert again.json()["oss_key"] == target["oss_key"]
    put = client.put(target["upload_url"], headers=target["headers"], content=image)
    assert put.status_code in (200, 204), put.text
    committed = client.post(
        "/gateway/frames", headers=headers, json={**body, "oss_key": target["oss_key"]}
    )
    assert committed.status_code == 201, committed.text
    from app.infrastructure.persistence.models import GatewayUploadReservation

    assert db.query(GatewayUploadReservation).count() == 0
    repeated = client.post(
        "/gateway/frames", headers=headers, json={**body, "oss_key": target["oss_key"]}
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == committed.json()["id"]
    renewed = client.post("/gateway/frames/upload-url", headers=headers, json=body)
    assert renewed.status_code == 200
    assert db.query(GatewayUploadReservation).count() == 0
    assert db.query(Frame).filter_by(ward_id=ward).count() == 1
    assert (
        db.query(OutboxEvent).filter_by(event_type="LearningFactRecorded.v1").count()
        == 1
    )
    altered = {**body, "sha256": "0" * 64}
    assert (
        client.post(
            "/gateway/frames/upload-url", headers=headers, json=altered
        ).status_code
        == 409
    )
    # Once issued, a gateway object may not be overwritten with different bytes.
    assert (
        client.put(
            target["upload_url"], headers=target["headers"], content=b"other"
        ).status_code
        == 409
    )


def test_gateway_rejects_wrong_object_time_and_revoked_camera(client, gateway, db):
    ward, headers = gateway
    reg = client.post(
        "/gateway/cameras",
        headers=headers,
        json={"camera_id": "camera-01", "ward_id": ward},
    ).json()
    body = {
        "camera_id": "camera-01",
        "ward_id": ward,
        "assignment_revision": 1,
        "frame_id": str(uuid4()),
        "captured_at": "2000-01-01T00:00:00Z",
        "sha256": "a" * 64,
        "size_bytes": 50,
        "content_type": "image/jpeg",
    }
    assert (
        client.post(
            "/gateway/frames/upload-url", headers=headers, json=body
        ).status_code
        == 422
    )
    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    client.post("/gateway/frames/upload-url", headers=headers, json=body).json()
    assert (
        client.post(
            "/gateway/frames", headers=headers, json={**body, "oss_key": "another/key"}
        ).status_code
        == 409
    )
    camera = db.get(Device, reg["device_id"])
    camera.gateway_enabled = False
    db.commit()
    assert (
        client.post(
            "/gateway/frames/upload-url", headers=headers, json=body
        ).status_code
        == 403
    )


def test_gateway_heartbeat_boot_order(client, gateway):
    ward, headers = gateway
    client.post(
        "/gateway/cameras",
        headers=headers,
        json={"camera_id": "camera-01", "ward_id": ward},
    )
    boot = str(uuid4())
    body = {
        "boot_id": boot,
        "sequence": 2,
        "cameras": [
            {
                "camera_id": "camera-01",
                "queue_frames": 3,
                "queue_bytes": 10,
                "dropped_count": 0,
                "last_error_code": "capture_failed",
            }
        ],
    }
    assert (
        client.post("/gateway/heartbeat", headers=headers, json=body).status_code == 200
    )
    body["sequence"] = 1
    assert (
        client.post("/gateway/heartbeat", headers=headers, json=body).status_code == 409
    )


def test_gateway_object_validation_cross_camera_and_boot_replay(client, gateway, db):
    ward, headers = gateway
    for camera in ("one", "two"):
        assert (
            client.post(
                "/gateway/cameras",
                headers=headers,
                json={"camera_id": camera, "ward_id": ward},
            ).status_code
            == 201
        )
    image = b"\xff\xd8correct\xff\xd9"
    body = {
        "camera_id": "one",
        "ward_id": ward,
        "assignment_revision": 1,
        "frame_id": str(uuid4()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(image).hexdigest(),
        "size_bytes": len(image),
    }
    target = client.post(
        "/gateway/frames/upload-url", headers=headers, json=body
    ).json()
    assert (
        client.post(
            "/gateway/frames",
            headers=headers,
            json={**body, "oss_key": target["oss_key"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/gateway/frames/upload-url",
            headers=headers,
            json={**body, "camera_id": "two"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            target["upload_url"],
            headers=target["headers"],
            content=b"\xff\xd8changed\xff\xd9",
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/gateway/frames",
            headers=headers,
            json={**body, "oss_key": target["oss_key"]},
        ).status_code
        == 409
    )
    first, second = str(uuid4()), str(uuid4())
    health = {"sequence": 1, "cameras": []}
    assert (
        client.post(
            "/gateway/heartbeat", headers=headers, json={**health, "boot_id": first}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/gateway/heartbeat", headers=headers, json={**health, "boot_id": second}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/gateway/heartbeat",
            headers=headers,
            json={**health, "boot_id": first, "sequence": 100},
        ).status_code
        == 409
    )


def test_gateway_orphan_cleanup_never_deletes_accepted_object(
    client, gateway, db, monkeypatch
):
    from datetime import timedelta

    from app.infrastructure.persistence.models import GatewayUploadReservation
    from app.infrastructure.storage.object_storage import storage
    from app.workers.celery_tasks import cleanup_gateway_uploads

    ward, headers = gateway
    client.post(
        "/gateway/cameras", headers=headers, json={"camera_id": "cam", "ward_id": ward}
    )
    image = b"\xff\xd8jpeg\xff\xd9"
    keys = []
    for accept in (False, True):
        body = {
            "camera_id": "cam",
            "ward_id": ward,
            "assignment_revision": 1,
            "frame_id": str(uuid4()),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(image).hexdigest(),
            "size_bytes": len(image),
        }
        target = client.post(
            "/gateway/frames/upload-url", headers=headers, json=body
        ).json()
        assert (
            client.put(
                target["upload_url"], headers=target["headers"], content=image
            ).status_code
            == 204
        )
        keys.append(target["oss_key"])
        if accept:
            assert (
                client.post(
                    "/gateway/frames",
                    headers=headers,
                    json={**body, "oss_key": target["oss_key"]},
                ).status_code
                == 201
            )
    for reservation in db.query(GatewayUploadReservation).all():
        reservation.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()
    monkeypatch.setattr("app.workers.celery_tasks.SessionLocal", lambda: db)
    assert cleanup_gateway_uploads.run() == 1
    assert not storage.exists(keys[0])
    assert storage.exists(keys[1])


def test_gateway_config_rejects_duplicate_credentials_and_hides_secrets(monkeypatch):
    from app.bootstrap.settings import ConfigurationError
    from app.infrastructure.security.gateway import credentials

    token = "do-not-show-this-secret"
    monkeypatch.setattr(
        "app.infrastructure.security.gateway.credential_config", lambda: token
    )
    with pytest.raises(ConfigurationError) as error:
        credentials()
    assert token not in str(error.value)


def test_erasing_ward_data_cannot_silently_reactivate_gateway(client, gateway, db):
    from app.infrastructure.persistence.models import GuardianWard
    from app.infrastructure.security.tokens import create_access_token
    from tests.support.factories import create_guardian

    ward, headers = gateway
    guardian = create_guardian(db)
    db.add(GuardianWard(guardian_id=guardian.id, ward_id=ward))
    db.commit()
    camera = {"camera_id": "camera-01", "ward_id": ward}
    assert (
        client.post("/gateway/cameras", headers=headers, json=camera).status_code == 201
    )
    image = b"\xff\xd8jpeg\xff\xd9"
    body = {
        "camera_id": "camera-01",
        "ward_id": ward,
        "assignment_revision": 1,
        "frame_id": str(uuid4()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(image).hexdigest(),
        "size_bytes": len(image),
    }
    target = client.post(
        "/gateway/frames/upload-url", headers=headers, json=body
    ).json()
    token = create_access_token(user_id=guardian.id, role="guardian")
    erased = client.delete(
        f"/wards/{ward}/data", headers={"Authorization": f"Bearer {token}"}
    )
    assert erased.status_code == 204, erased.text
    repeat = client.post("/gateway/cameras", headers=headers, json=camera)
    assert repeat.status_code == 403, repeat.text
    assert repeat.json()["error_code"] == "WARD_DATA_ERASED"
    visible = client.get(
        f"/wards/{ward}/devices", headers={"Authorization": f"Bearer {token}"}
    )
    assert visible.json() == []

    # Short-lived signed PUTs cannot be revoked; their keys remain tracked.
    assert (
        client.put(
            target["upload_url"], headers=target["headers"], content=image
        ).status_code
        == 204
    )
    from datetime import timedelta

    from app.application.commands.gateway_ingestion import CleanupGatewayUploads
    from app.infrastructure.persistence.gateway_repository import SqlCaptureRepository
    from app.infrastructure.storage.object_storage import storage

    assert (
        CleanupGatewayUploads(SqlCaptureRepository(db), storage).run(
            datetime.now(timezone.utc) + timedelta(hours=25)
        )
        == 1
    )
    assert not storage.exists(target["oss_key"])


def test_cleanup_pages_old_reservations_and_retires_legacy_accepted_rows(db):
    from datetime import timedelta

    from app.application.commands.gateway_ingestion import CleanupGatewayUploads
    from app.infrastructure.persistence.gateway_repository import SqlCaptureRepository
    from app.infrastructure.persistence.models import GatewayUploadReservation

    ward = Ward(id=str(uuid4()), display_name="cleanup", grade_stage="primary")
    db.add(ward)
    db.flush()
    device = Device(ward_id=ward.id, gateway_id="cleanup", camera_id="cam")
    db.add(device)
    db.flush()
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    reservations = [
        GatewayUploadReservation(
            gateway_id="cleanup",
            frame_id=str(uuid4()),
            device_id=device.id,
            oss_key=f"cleanup/{i}",
            fingerprint="0" * 64,
            created_at=old,
        )
        for i in range(1007)
    ]
    accepted = reservations[0]
    db.add_all(reservations)
    db.add(
        Frame(
            gateway_id="cleanup",
            gateway_frame_id=accepted.frame_id,
            device_id=device.id,
            ward_id=ward.id,
            oss_key=accepted.oss_key,
            captured_at=old,
            purge_after=old + timedelta(days=90),
        )
    )
    db.commit()

    class RecordingStorage:
        def __init__(self):
            self.deleted = []

        def delete(self, key):
            self.deleted.append(key)

    repository = SqlCaptureRepository(db)
    original = repository.orphan_candidates
    batches = []

    def candidates(*args, **kwargs):
        batch = original(*args, **kwargs)
        batches.append(len(batch))
        return batch

    repository.orphan_candidates = candidates
    storage = RecordingStorage()
    assert (
        CleanupGatewayUploads(repository, storage).run(datetime.now(timezone.utc))
        == 1006
    )
    assert accepted.oss_key not in storage.deleted
    assert batches == [500, 500, 7, 0]
    assert db.query(GatewayUploadReservation).count() == 0
