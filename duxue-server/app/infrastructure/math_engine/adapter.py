"""No local execution fallback: missing isolated executor means unavailable."""

import json
import socket

from app.application.ports.math_engine import MathInput, MathResult


class MathEngineAdapter:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def execute(self, request: MathInput) -> MathResult:
        payload = (
            json.dumps(request.model_dump(exclude={"image_ref", "step_ref"})).encode()
            + b"\n"
        )
        if len(payload) > 16384:
            return MathResult(status="error", error_code="resource_limit")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3.0)
                client.connect(self.socket_path)
                client.sendall(payload)
                with client.makefile("rb") as stream:
                    raw = stream.readline(16385)
                if len(raw) > 16384 or not raw.endswith(b"\n"):
                    raise ValueError("invalid_executor_response")
                return MathResult.model_validate_json(raw)
        except (OSError, ValueError):
            return MathResult(status="unknown", error_code="unavailable")
