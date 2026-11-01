import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def test_gateway_provisioning_is_private_and_non_overwriting(tmp_path):
    script = (
        Path(__file__).resolve().parents[3] / "scripts/create_gateway_credentials.py"
    )
    target = tmp_path / "private"
    ward = str(uuid4())
    args = [
        sys.executable,
        str(script),
        "--gateway-id",
        "home-01",
        "--ward-id",
        ward,
        "--output-dir",
        str(target),
    ]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    token = (target / "gateway.env").read_text().split("=", 1)[1].strip().strip("'")
    config = json.loads(
        (target / "server.env").read_text().split("=", 1)[1].strip().strip("'")
    )
    assert config[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert config[0]["allowed_ward_ids"] == [ward]
    assert token not in result.stdout + result.stderr
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / "gateway.env").stat().st_mode & 0o777 == 0o600
    assert subprocess.run(args, check=False, capture_output=True).returncode != 0
    assert token in (target / "gateway.env").read_text()
