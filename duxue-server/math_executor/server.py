"""Unix-only transport. Production isolation is enforced by docker-compose.math.yml."""

from __future__ import annotations

import json
import os
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

MAX_WIRE = 16384
TIMEOUT = 2.0
WORKER = Path(__file__).with_name("worker.py")


def failure(code):
    return {
        "status": "unknown",
        "error_code": code,
        "conditions": [],
        "checked_scope": "value",
    }


def compute(request, *, timeout=TIMEOUT, worker=WORKER):
    payload = json.dumps(request).encode()
    if len(payload) > MAX_WIRE:
        return failure("resource_limit")
    # No business environment, working directory, shell, or inherited file descriptors.
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(
            [sys.executable, "-I", str(worker)],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C.UTF-8"},
            cwd="/tmp",
            close_fds=True,
            start_new_session=True,
        )
        try:
            child.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate()
            return failure("timeout")
        if child.returncode:
            return failure("resource_limit")
        output.seek(0)
        body = output.read(MAX_WIRE + 1)
        if len(body) > MAX_WIRE:
            return failure("resource_limit")
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            return failure("invalid_input")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        try:
            raw = self.rfile.readline(MAX_WIRE + 1)
            if len(raw) > MAX_WIRE or not raw.endswith(b"\n"):
                result = failure("invalid_input")
            else:
                result = compute(json.loads(raw))
            self.wfile.write(json.dumps(result).encode() + b"\n")
        except (ValueError, OSError):
            return


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 4

    def __init__(self, address):
        self.slots = threading.BoundedSemaphore(2)
        super().__init__(address, Handler)
        os.chmod(
            address, 0o666
        )  # Access controlled by the dedicated socket-volume mount.

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(json.dumps(failure("resource_limit")).encode() + b"\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


if __name__ == "__main__":
    path = os.environ.get("MATH_SOCKET", "/run/math/engine.sock")
    Path(path).unlink(missing_ok=True)
    with Server(path) as server:
        server.serve_forever()
