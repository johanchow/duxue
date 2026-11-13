import json
import os
import socket
import threading

import pytest

from app.application.ports.math_engine import MathInput
from app.infrastructure.math_engine.adapter import MathEngineAdapter
from math_executor.server import Server, compute


def test_real_worker_computes_without_business_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "secret-must-not-be-inherited")
    result = compute({"op": "evaluate", "args": {"expression": "2+3"}})
    assert result["status"] == "ok"
    assert result["result"] == "5"


def test_timeout_kills_and_reaps_child(tmp_path):
    script = tmp_path / "slow.py"
    marker = tmp_path / "pid"
    script.write_text(
        f'import os,time\nopen({str(marker)!r},"w").write(str(os.getpid()))\ntime.sleep(20)\n'
    )
    assert compute({}, timeout=0.3, worker=script)["error_code"] == "timeout"
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_worker_receives_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "private")
    script = tmp_path / "env.py"
    script.write_text("import os,json\nprint(json.dumps(dict(os.environ)))")
    env = compute({}, worker=script)
    assert "DATABASE_URL" not in env
    assert "HOME" not in env
    # macOS CoreFoundation can inject its encoding marker after exec even
    # though Popen receives only LANG. Business variables must remain absent.
    allowed = {"LANG", "LC_CTYPE"}
    import sys
    if sys.platform == "darwin":
        allowed.add("__CF_USER_TEXT_ENCODING")
    assert set(env) <= allowed


def test_real_unix_transport_and_missing_executor(tmp_path):
    # macOS Unix socket path limit is smaller than pytest's temporary directory.
    import tempfile

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="math-") as short:
        path = short + "/engine.sock"
        server = Server(path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = MathEngineAdapter(path)
            result = adapter.execute(
                MathInput(op="evaluate", args={"expression": "1/3+1/6"})
            )
            assert result.result == "1/2"
            assert result.status == "ok"
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(2)
                client.connect(path)
                client.sendall(b"x" * 16385)
                assert json.loads(client.recv(4096))["status"] != "ok"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        assert (
            MathEngineAdapter(path)
            .execute(MathInput(op="evaluate", args={"expression": "1"}))
            .status
            == "unknown"
        )


def test_compose_has_enforced_permission_boundaries():
    from pathlib import Path

    import yaml

    spec = yaml.safe_load(Path("docker-compose.math.yml").read_text())
    engine = spec["services"]["math-engine"]
    assert engine["network_mode"] == "none"
    assert engine["read_only"] is True
    assert engine["user"] != "root"
    assert engine["cap_drop"] == ["ALL"]
    assert "env_file" not in engine
    assert engine["pids_limit"] == 16
    assert not any("/var/run/docker.sock" in v for v in engine["volumes"])
