"""A real HTTP-level vertical slice using SQLite and local object storage."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp.name) / 'test.db'}"
os.environ["LOCAL_UPLOAD_DIR"] = str(Path(_tmp.name) / "uploads")
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        _tmp.cleanup()

    def request(self, method, path, *, token=None, device_token=None, **kwargs):
        auth = token or device_token
        headers = kwargs.pop("headers", {})
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        return self.client.request(method, path, headers=headers, **kwargs)

    def test_complete_capture_to_report_flow_and_tenant_isolation(self):
        registration = self.request("POST", "/auth/register", json={
            "name": "监护人", "email": "guardian@example.com", "password": "password123",
        })
        self.assertEqual(registration.status_code, 201, registration.text)
        guardian_token = registration.json()["access_token"]

        ward_response = self.request("POST", "/wards", token=guardian_token, json={"display_name": "小读"})
        self.assertEqual(ward_response.status_code, 201, ward_response.text)
        ward_id = ward_response.json()["id"]

        invite = self.request("POST", f"/wards/{ward_id}/devices/invite", token=guardian_token)
        self.assertEqual(invite.status_code, 201, invite.text)
        bound = self.request("POST", "/devices/bind", json={
            "invite_code": invite.json()["invite_code"], "elapsed_realtime": 1_000,
        })
        self.assertEqual(bound.status_code, 200, bound.text)
        device_token = bound.json()["device_token"]
        heartbeat = self.request("POST", "/devices/heartbeat", device_token=device_token)
        self.assertEqual(heartbeat.json()["status"], "online")

        frame_ids = []
        base = datetime.now(timezone.utc).replace(microsecond=0)
        descriptions = [
            {"hand_action": "右手握笔书写", "seat_status": "在座"},
            {"hand_action": "双手捧着手机", "seat_status": "在座"},
            {"hand_action": "右手握笔书写", "seat_status": "在座"},
        ]
        for index in range(3):
            signed = self.request("POST", "/frames/upload-url", device_token=device_token, json={"extension": "jpg"})
            self.assertEqual(signed.status_code, 200, signed.text)
            upload = self.client.put(signed.json()["upload_url"], content=b"fake-jpeg-bytes")
            self.assertEqual(upload.status_code, 204, upload.text)
            ingested = self.request("POST", "/frames", device_token=device_token, json={
                "oss_key": signed.json()["oss_key"],
                "captured_at": (base + timedelta(seconds=index * 15)).isoformat(),
                "elapsed_realtime": 1_000 + index * 15_000,
            })
            self.assertEqual(ingested.status_code, 201, ingested.text)
            frame_ids.append(ingested.json()["id"])

        pending = self.request("GET", f"/reports/daily?ward_id={ward_id}&date={base.date()}", token=guardian_token)
        self.assertEqual(pending.json()["status"], "processing")
        analysis = self.request("POST", "/analysis/run", token=guardian_token, json={
            "ward_id": ward_id, "report_date": str(base.date()),
            "results": dict(zip(frame_ids, descriptions)),
        })
        self.assertEqual(analysis.status_code, 200, analysis.text)
        report = analysis.json()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["total_seconds"], 45)
        # The isolated phone frame is removed by the three-frame majority smoother.
        self.assertEqual(report["label_breakdown"], {"学习": 45})

        outsider = self.request("POST", "/auth/register", json={
            "name": "其他租户", "email": "other@example.com", "password": "password123",
        }).json()["access_token"]
        forbidden_by_isolation = self.request(
            "GET", f"/reports/daily?ward_id={ward_id}&date={base.date()}", token=outsider,
        )
        self.assertEqual(forbidden_by_isolation.status_code, 404)


if __name__ == "__main__":
    unittest.main()
