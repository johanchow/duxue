"""Opt-in live Go binary → FastAPI → local immutable storage smoke test.

Set GATEWAY_BINARY_PATH to a built gateway; no real camera/OSS credentials used.
"""

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infrastructure.persistence.database import Base
from app.infrastructure.persistence.models import Frame, OutboxEvent, User, Ward


def available_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_live_gateway_binary_and_restart(tmp_path):
    binary = os.getenv("GATEWAY_BINARY_PATH")
    if not binary:
        pytest.skip("GATEWAY_BINARY_PATH enables live binary integration")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for synthetic JPEG fixture")
    image = subprocess.check_output(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x64",
            "-frames:v",
            "1",
            "-c:v",
            "mjpeg",
            "-threads",
            "1",
            "-f",
            "image2pipe",
            "pipe:1",
        ],
        timeout=10,
    )

    class Camera(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(image)

        def log_message(self, *args):
            pass

    camera = ThreadingHTTPServer(("127.0.0.1", 0), Camera)
    thread = threading.Thread(target=camera.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[2]
    db_url = f"sqlite:///{tmp_path / 'server.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    ward_id = str(uuid4())
    with Session(engine) as db:
        db.add(User(id=ward_id, type="ward"))
        db.flush()
        db.add(Ward(id=ward_id, display_name="smoke", grade_stage="primary"))
        db.commit()
    token = "synthetic-gateway-test-token"
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "LOCAL_UPLOAD_DIR": str(tmp_path / "objects"),
        "STORAGE_BACKEND": "local",
        "ENV_FILE": "/dev/null",
        "SECRET_KEY": "smoke-only",
        "JWT_SECRET_KEY": "smoke-only",
        "VLM_API_KEY": "smoke-only",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "OTEL_SDK_DISABLED": "true",
        "GATEWAY_CREDENTIALS_JSON": json.dumps(
            [
                {
                    "gateway_id": "smoke",
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "allowed_ward_ids": [ward_id],
                }
            ]
        ),
        "SMOKE_GATEWAY_TOKEN": token,
    }
    port = available_port()
    base = f"http://127.0.0.1:{port}"
    config = tmp_path / "config.yaml"
    config.write_text(
        json.dumps(
            {
                "api_base_url": base,
                "api_token_env": "SMOKE_GATEWAY_TOKEN",
                "state_dir": str(tmp_path / "queue"),
                "capture_interval_seconds": 1,
                "cameras": [
                    {
                        "camera_id": "camera-01",
                        "ward_id": ward_id,
                        "source": {
                            "kind": "snapshot",
                            "url": f"http://127.0.0.1:{camera.server_port}/",
                        },
                    }
                ],
            }
        )
    )
    api_log = (tmp_path / "api.log").open("wb")
    gateway_log = (tmp_path / "gateway.log").open("wb")
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.bootstrap.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=root,
        env=env,
        stdout=api_log,
        stderr=api_log,
    )
    gateway = None
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/openapi.json", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("isolated API failed to start")
        check = subprocess.run(
            [binary, "config-check", "-config", str(config)],
            env=env,
            capture_output=True,
            check=False,
        )
        assert check.returncode == 0, check.stderr.decode()

        def launch():
            return subprocess.Popen(
                [binary, "run", "-config", str(config)],
                env=env,
                stdout=gateway_log,
                stderr=gateway_log,
            )

        gateway = launch()

        def wait_for_count(minimum):
            for _ in range(100):
                if gateway.poll() is not None:
                    pytest.fail(
                        "gateway exited: " + (tmp_path / "gateway.log").read_text()
                    )
                with Session(engine) as db:
                    if db.query(Frame).count() >= minimum:
                        return
                time.sleep(0.05)
            pytest.fail(
                "no capture progress: " + (tmp_path / "gateway.log").read_text()
            )

        wait_for_count(1)
        gateway.kill()
        gateway.wait(timeout=5)
        gateway = launch()
        wait_for_count(2)
        gateway.send_signal(signal.SIGTERM)
        assert gateway.wait(timeout=5) == 0
        status_env = {k: v for k, v in env.items() if k != "SMOKE_GATEWAY_TOKEN"}
        status = subprocess.run(
            [binary, "status", "-config", str(config)],
            env=status_env,
            capture_output=True,
            check=False,
        )
        assert status.returncode == 0, status.stderr.decode()
        assert json.loads(status.stdout)[0]["last_submit_at"]
        with Session(engine) as db:
            frames = db.query(Frame).all()
            assert len({f.gateway_frame_id for f in frames}) == len(frames)
            assert db.query(OutboxEvent).filter_by(
                event_type="LearningFactRecorded.v1"
            ).count() == len(frames)
            for frame in frames:
                assert frame.ward_id == ward_id
                data = (tmp_path / "objects" / frame.oss_key).read_bytes()
                assert hashlib.sha256(data).hexdigest() == frame.sha256
    finally:
        if gateway and gateway.poll() is None:
            gateway.kill()
            gateway.wait(timeout=5)
        api.terminate()
        api.wait(timeout=5)
        api_log.close()
        gateway_log.close()
        camera.shutdown()
        camera.server_close()
        thread.join(timeout=2)
        engine.dispose()
    assert token not in (tmp_path / "gateway.log").read_text()
