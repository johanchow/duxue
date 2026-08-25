"""A real HTTP-level vertical slice using SQLite and local object storage."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone
from pathlib import Path


_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp.name) / 'test.db'}"
os.environ["LOCAL_UPLOAD_DIR"] = str(Path(_tmp.name) / "uploads")
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.storage import storage  # noqa: E402
from app.task_intake import TaskIntakeResult  # noqa: E402


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

    def test_complete_capture_to_report_flow_and_guardian_ward_isolation(self):
        registration = self.request("POST", "/auth/register", json={
            "name": "监护人", "email": "guardian@example.com", "password": "password123",
        })
        self.assertEqual(registration.status_code, 201, registration.text)
        guardian_token = registration.json()["access_token"]
        self.assertEqual(self.request("GET", "/admin/summary", token=guardian_token).status_code, 200)

        ward_response = self.request("POST", "/wards", token=guardian_token, json={"display_name": "小读", "grade_stage": "primary"})
        self.assertEqual(ward_response.status_code, 201, ward_response.text)
        self.assertEqual(ward_response.json()["grade_stage"], "primary")
        ward_id = ward_response.json()["id"]
        invalid_grade = self.request("POST", "/wards", token=guardian_token, json={"display_name": "无效学段", "grade_stage": "college"})
        self.assertEqual(invalid_grade.status_code, 422)

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
            "name": "其他家长", "email": "other@example.com", "password": "password123",
        }).json()["access_token"]
        forbidden_by_isolation = self.request(
            "GET", f"/reports/daily?ward_id={ward_id}&date={base.date()}", token=outsider,
        )
        self.assertEqual(forbidden_by_isolation.status_code, 404)

    def test_day_story_requires_ward_review_before_insights(self):
        token = self.request("POST", "/auth/register", json={"name":"家长2","email":"story@example.com","password":"password123"}).json()["access_token"]
        ward = self.request("POST", "/wards", token=token, json={"display_name":"小读2", "grade_stage":"middle"}).json()["id"]
        assignment = self.request("POST", f"/wards/{ward}/assignments", token=token, json={"title":"数学作业"})
        self.assertEqual(assignment.status_code, 201)
        invite = self.request("POST", f"/wards/{ward}/login-invite", token=token).json()
        ward_token = self.request("POST", "/ward-auth/bind", json={"invite_code":invite["invite_code"]}).json()["access_token"]
        day = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(self.request("GET", f"/wards/{ward}/guardian-story/{day}", token=token).json()["status"], "locked")
        assignment_id = self.request("GET", f"/wards/{ward}/assignments", token=ward_token).json()[0]["id"]
        self.assertEqual(self.request("PUT", f"/wards/{ward}/plans/{day}", token=ward_token, json={"plan_date":day,"items":[{"assignment_id":assignment_id,"title":"数学作业","planned_minutes":30}]}).status_code, 200)
        self.assertEqual(self.request("POST", f"/wards/{ward}/plans/{day}/confirm", token=ward_token).status_code, 200)
        plan = self.request("GET", f"/wards/{ward}/plans/{day}", token=ward_token).json()
        guardian_plan = self.request("GET", f"/wards/{ward}/plans/{day}", token=token)
        self.assertEqual(guardian_plan.status_code, 200, guardian_plan.text)
        self.assertEqual(guardian_plan.json()["status"], "confirmed")
        session = self.request("POST", f"/plan-items/{plan['items'][0]['id']}/sessions", token=ward_token).json()["id"]
        self.assertEqual(self.request("POST", f"/sessions/{session}/messages", token=ward_token, json={"content":"我不会这题"}).json()["mode"], "socratic")
        self.assertEqual(self.request("POST", f"/sessions/{session}/finish", token=ward_token, json={"active_seconds":1800}).status_code, 200)
        self.assertEqual(self.request("POST", f"/wards/{ward}/reviews/{day}", token=ward_token, json={"feeling":"顺利","timeline_json":[]}).status_code, 200)
        self.assertEqual(self.request("GET", f"/wards/{ward}/reviews/{day}/insight", token=ward_token).json()["status"], "ready")
        self.assertEqual(self.request("GET", f"/wards/{ward}/guardian-story/{day}", token=token).json()["status"], "ready")

    def test_ward_can_pause_and_complete_planned_or_unplanned_tasks(self):
        guardian = self.request("POST", "/auth/register", json={"name":"执行家长", "email":"execution@example.com", "password":"password123"}).json()["access_token"]
        ward = self.request("POST", "/wards", token=guardian, json={"display_name":"小执行", "grade_stage":"middle"}).json()["id"]
        first = self.request("POST", f"/wards/{ward}/assignments", token=guardian, json={"title":"计划内任务"}).json()["id"]
        second = self.request("POST", f"/wards/{ward}/assignments", token=guardian, json={"title":"任务池任务"}).json()["id"]
        invite = self.request("POST", f"/wards/{ward}/login-invite", token=guardian).json()
        ward_token = self.request("POST", "/ward-auth/bind", json={"invite_code":invite["invite_code"]}).json()["access_token"]
        day = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(self.request("PUT", f"/wards/{ward}/plans/{day}", token=ward_token, json={"plan_date":day,"items":[{"assignment_id":first,"title":"计划内任务","planned_minutes":30}]}).status_code, 200)
        self.assertEqual(self.request("POST", f"/wards/{ward}/plans/{day}/confirm", token=ward_token).status_code, 200)
        plan_item = self.request("GET", f"/wards/{ward}/plans/{day}", token=ward_token).json()["items"][0]
        planned_session = self.request("POST", f"/plan-items/{plan_item['id']}/sessions", token=ward_token).json()["id"]
        self.assertEqual(self.request("POST", f"/sessions/{planned_session}/pause", token=ward_token, json={"active_seconds":12}).json()["status"], "paused")
        self.assertEqual(self.request("POST", f"/sessions/{planned_session}/resume", token=ward_token).json()["status"], "active")
        self.assertEqual(self.request("POST", f"/sessions/{planned_session}/finish", token=ward_token, json={"active_seconds":30}).status_code, 200)
        pool_session = self.request("POST", f"/assignments/{second}/sessions", token=ward_token).json()["id"]
        self.assertEqual(self.request("POST", f"/sessions/{pool_session}/pause", token=ward_token, json={"active_seconds":9}).json()["status"], "paused")
        assignments = self.request("GET", f"/wards/{ward}/assignments", token=ward_token).json()
        self.assertEqual(next(item for item in assignments if item["id"] == second)["session"]["status"], "paused")
        self.assertEqual(self.request("POST", f"/sessions/{pool_session}/resume", token=ward_token).status_code, 200)
        self.assertEqual(self.request("POST", f"/sessions/{pool_session}/finish", token=ward_token, json={"active_seconds":20}).status_code, 200)
        self.assertNotIn(second, {item["id"] for item in self.request("GET", f"/wards/{ward}/assignments", token=ward_token).json()})

    def test_ward_profile_exposes_its_guardian_name(self):
        guardian = self.request("POST", "/auth/register", json={"name":"林妈妈", "email":"profile@example.com", "password":"password123"}).json()["access_token"]
        ward = self.request("POST", "/wards", token=guardian, json={"display_name":"小宇", "grade_stage":"primary"}).json()["id"]
        invite = self.request("POST", f"/wards/{ward}/login-invite", token=guardian).json()
        ward_token = self.request("POST", "/ward-auth/bind", json={"invite_code":invite["invite_code"]}).json()["access_token"]
        profile = self.request("GET", "/ward/profile", token=ward_token)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["display_name"], "小宇")
        self.assertEqual([item["name"] for item in profile.json()["guardians"]], ["林妈妈"])

    def test_guardian_voice_socket_streams_partial_and_final_text(self):
        token = self.request("POST", "/auth/register", json={"name": "语音家长", "email": "voice@example.com", "password": "password123"}).json()["access_token"]
        ward = self.request("POST", "/wards", token=token, json={"display_name": "小语", "grade_stage": "high"}).json()["id"]

        class FakeAsr:
            async def send_audio(self, chunk): self.chunk = chunk
            async def commit(self): self.committed = True
            async def finish(self): pass
            async def close(self): pass
            async def events(self):
                yield {"type": "partial", "text": "安排明天的数"}
                yield {"type": "final", "text": "安排明天的数学作业"}

        with patch("app.main.DashscopeRealtimeAsr.connect", new=AsyncMock(return_value=FakeAsr())):
            with self.client.websocket_connect("/ws/asr/transcribe", headers={"Authorization": f"Bearer {token}"}) as socket:
                socket.send_json({"type": "start"})
                self.assertEqual(socket.receive_json()["type"], "ready")
                socket.send_bytes(b"pcm")
                socket.send_json({"type": "commit"})
                self.assertEqual(socket.receive_json(), {"type": "partial", "text": "安排明天的数"})
                self.assertEqual(socket.receive_json(), {"type": "final", "text": "安排明天的数学作业"})

    def test_ward_rebinding_uses_one_time_six_digit_code_and_revokes_old_session(self):
        guardian = self.request("POST", "/auth/register", json={"name": "换机家长", "email": "rebind@example.com", "password": "password123"}).json()["access_token"]
        ward = self.request("POST", "/wards", token=guardian, json={"display_name": "小换", "grade_stage": "primary"}).json()["id"]
        first_code = self.request("POST", f"/wards/{ward}/login-invite", token=guardian).json()["invite_code"]
        self.assertRegex(first_code, r"^\d{6}$")
        old_token = self.request("POST", "/ward-auth/bind", json={"invite_code": first_code}).json()["access_token"]
        self.assertEqual(self.request("POST", "/ward-auth/bind", json={"invite_code": first_code}).status_code, 400)

        replacement_code = self.request("POST", f"/wards/{ward}/login-invite", token=guardian).json()["invite_code"]
        self.assertRegex(replacement_code, r"^\d{6}$")
        new_token = self.request("POST", "/ward-auth/bind", json={"invite_code": replacement_code})
        self.assertEqual(new_token.status_code, 200, new_token.text)

        self.assertEqual(self.request("GET", f"/wards/{ward}/assignments", token=old_token).status_code, 401)
        self.assertEqual(self.request("GET", f"/wards/{ward}/assignments", token=new_token.json()["access_token"]).status_code, 200)

    def test_task_intake_requires_llm_clarification_then_confirms_only_owned_wards(self):
        token = self.request("POST", "/auth/register", json={"name": "多孩家长", "email": "intake@example.com", "password": "password123"}).json()["access_token"]
        first = self.request("POST", "/wards", token=token, json={"display_name": "小宇", "grade_stage": "primary"}).json()["id"]
        second = self.request("POST", "/wards", token=token, json={"display_name": "小雨", "grade_stage": "middle"}).json()["id"]
        ambiguous = TaskIntakeResult(
            assistant_text="这项作业是给小宇还是小雨？", clarification_required=True,
            questions=["请说明任务归属"], ready_to_confirm=False,
        )
        with patch("app.main.TaskIntakeService.respond", return_value=ambiguous):
            response = self.request("POST", "/task-intake/respond", token=token, json={"content": "明天交数学作业"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["ready_to_confirm"])
        self.assertEqual(response.json()["tasks"], [])

        parsed = TaskIntakeResult(
            assistant_text="已整理两项任务。",
            tasks=[
                {"ward_id": first, "title": "数学作业"},
                {"ward_id": second, "title": "英语朗读", "details": "朗读课文"},
            ], ready_to_confirm=True,
        )
        signed = self.request("POST", "/task-intake/upload-url", token=token, json={"extension": "jpg", "content_type": "image/jpeg"})
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertEqual(self.client.put(signed.json()["upload_url"], content=b"task-image").status_code, 204)
        attachment = signed.json()["oss_key"]
        with patch("app.main.TaskIntakeService.respond", return_value=parsed):
            response = self.request("POST", "/task-intake/respond", token=token, json={"content": "数学给小宇，英语朗读给小雨", "attachment_keys": [attachment]})
        self.assertTrue(response.json()["ready_to_confirm"])
        confirmation = self.request("POST", "/task-intake/confirm", token=token, json={"tasks": response.json()["tasks"], "attachment_keys": [attachment]})
        self.assertEqual(confirmation.status_code, 201, confirmation.text)
        self.assertEqual({item["ward_id"] for item in confirmation.json()["assignments"]}, {first, second})
        self.assertFalse(storage.exists(attachment))

        outsider = self.request("POST", "/auth/register", json={"name": "外部家长", "email": "intake-other@example.com", "password": "password123"}).json()["access_token"]
        foreign = self.request("POST", "/wards", token=outsider, json={"display_name": "外部孩子", "grade_stage": "high"}).json()["id"]
        rejected = self.request("POST", "/task-intake/confirm", token=token, json={"tasks": [{"ward_id": foreign, "title": "不应写入"}]})
        self.assertEqual(rejected.status_code, 404)


if __name__ == "__main__":
    unittest.main()
