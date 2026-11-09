"""Pull releases, retain last known good, and pin one immutable definition set per turn."""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import httpx

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.definitions import pinned_definitions, use_definitions


class ReleaseRuntime:
    def __init__(self, source: str, token: str, cache: Path):
        self.source, self.token, self.cache = source.rstrip("/"), token, cache
        self.current = None
        self.last_error = None
        self.stop_event = threading.Event()
        self.thread = None
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}"

    def accept(self, release):
        snapshot = compile_bundle(release["bundle"])
        if release["digest"] != snapshot.digest:
            raise ValueError("release digest mismatch")
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(release, ensure_ascii=False))
        temporary.chmod(0o600)
        temporary.replace(self.cache)
        self.current = (release, snapshot)

    def tick(self):
        headers = {"Authorization": "Bearer " + self.token}
        target = None
        try:
            response = httpx.get(self.source + "/release", headers=headers, timeout=5)
            response.raise_for_status()
            target = response.json()
            if target.get("release"):
                incoming = target["release"]
                if self.current is None or self.current[0]["id"] != incoming["id"]:
                    self.accept(incoming)
            self.last_error = None
        except Exception as error:  # noqa: BLE001 - keep the last successful configuration
            self.last_error = (
                str(error)[:200]
                if isinstance(error, ValueError)
                else type(error).__name__
            )
        current = self.current[0] if self.current else {}
        try:
            httpx.post(
                self.source + "/ack",
                headers=headers,
                timeout=5,
                json={
                    "instance_id": self.instance_id,
                    "release_id": current.get("id"),
                    "digest": current.get("digest"),
                    "status": "failed" if self.last_error else "loaded",
                    "error": self.last_error,
                },
            ).raise_for_status()
        except Exception as error:  # noqa: BLE001 - next poll retries the acknowledgement
            logging.getLogger(__name__).warning(
                "agent config acknowledgement failed: %s", type(error).__name__
            )

    def definitions(self):
        if self.current is None:
            raise AgentConfigurationUnavailable("No compatible Admin release is loaded")
        return self.current[1].catalog

    @contextmanager
    def pin(self):
        current = self.current
        if current is None:
            self.definitions()  # Admin mode never silently executes code defaults.
        else:
            with use_definitions(current[1].catalog):
                from opentelemetry import trace

                span = trace.get_current_span()
                span.set_attribute("agent.release.id", current[0]["id"])
                span.set_attribute("agent.release.digest", current[1].digest)
                yield

    def start(self):
        if self.cache.is_file():
            try:
                self.accept(json.loads(self.cache.read_text()))
            except Exception:  # noqa: BLE001 - invalid cache must not prevent startup
                self.last_error = "invalid_cached_release"

        def poll():
            while not self.stop_event.is_set():
                self.tick()
                self.stop_event.wait(30)

        self.thread = threading.Thread(
            target=poll, daemon=True, name="agent-config-pull"
        )
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)


class AgentConfigurationUnavailable(RuntimeError):
    pass


runtime = None


def start_runtime():
    global runtime
    source = os.getenv("AGENT_CONFIG_SOURCE_URL", "")
    token = os.getenv("AGENT_ADMIN_INTERNAL_TOKEN", "")
    if source and token and os.getenv("APP_ENV", "test") not in {"production", "prod"}:
        runtime = ReleaseRuntime(
            source,
            token,
            Path(os.getenv("AGENT_CONFIG_CACHE", "var/admin/last-good.json")),
        )
        runtime.start()


def close_runtime():
    if runtime:
        runtime.close()


@contextmanager
def pin_release():
    if pinned_definitions() is not None:
        yield
    elif runtime:
        with runtime.pin():
            yield
    else:
        yield


def configured_call(function):
    """Pin an entire application call, including context building and retries."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with pin_release():
            return function(*args, **kwargs)

    return wrapped
