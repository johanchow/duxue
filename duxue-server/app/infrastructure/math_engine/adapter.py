"""No local execution fallback: missing isolated executor means unavailable."""

import json
import socket

from app.application.ports.math_engine import MathInput, MathResult


class _IsolatedMathAdapter:
    def execute(self, request: MathInput) -> MathResult:
        try:
            return MathResult.model_validate(self._exchange(request.model_dump(exclude={"image_ref", "step_ref"})))
        except ValueError:
            return MathResult(status="unknown", error_code="unavailable")

    def check_arithmetic(self, pairs, timeout):
        response = self._exchange({"worksheet_arithmetic": pairs}, timeout=timeout)
        values = response.get("results")
        if (isinstance(values, list) and len(values) == len(pairs)
                and all(v in ("equal", "not_equal", "invalid_input") for v in values)):
            return values
        code = response.get("error_code")
        return [code if code in ("timeout", "resource_limit") else "unavailable"] * len(pairs)


class MathEngineAdapter(_IsolatedMathAdapter):
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def _exchange(self, request, timeout=3.0):
        payload = json.dumps(request, ensure_ascii=False).encode() + b"\n"
        if len(payload) > 16384:
            return {"status": "error", "error_code": "resource_limit"}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(min(timeout, 3.0))
                client.connect(self.socket_path)
                client.sendall(payload)
                with client.makefile("rb") as stream:
                    raw = stream.readline(16385)
                if len(raw) > 16384 or not raw.endswith(b"\n"):
                    raise ValueError("invalid_executor_response")
                response = json.loads(raw)
                return response if isinstance(response, dict) else {"status": "unknown", "error_code": "unavailable"}
        except TimeoutError:
            return {"status": "unknown", "error_code": "timeout"}
        except (OSError, ValueError):
            return {"status": "unknown", "error_code": "unavailable"}


class SubprocessMathEngineAdapter(_IsolatedMathAdapter):
    """Explicit non-production adapter running the isolated child worker directly."""

    def __init__(self, *, timeout: float = 2.0):
        self.timeout = timeout

    def _exchange(self, request, timeout=3.0):
        from math_executor.server import compute

        return compute(request, timeout=min(self.timeout, timeout))
