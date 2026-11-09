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
    def __init__(self, source: str, token: str, cache: Path, expected_environment=None):
        self.source, self.token, self.cache = source.rstrip("/"), token, cache
        self.expected_environment = expected_environment
        self.current = None
        self.last_error = None
        self.stop_event = threading.Event()
        self.thread = None
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}"

    def accept(self, release):
        if release.get("kind", "release") != "release":
            raise ValueError("在线运行只加载已发布配置")
        if self.expected_environment and release.get("environment") != self.expected_environment:
            raise ValueError("缓存配置环境不匹配")
        snapshot = compile_bundle(release["bundle"])
        if release["digest"] != snapshot.digest:
            raise ValueError("release digest mismatch")
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        descriptor, name = tempfile.mkstemp(prefix=".agent-release-", dir=self.cache.parent)
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(release, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            Path(name).replace(self.cache)
        finally:
            Path(name).unlink(missing_ok=True)
        self.current = (release, snapshot)

    def tick(self, *, acknowledge=True):
        headers = {"Authorization": "Bearer " + self.token}
        target = None
        try:
            response = httpx.get(self.source + "/release", headers=headers, timeout=5)
            response.raise_for_status()
            target = response.json()
            if self.expected_environment and target.get("environment") != self.expected_environment:
                raise ValueError("Admin环境不匹配，拒绝加载其他环境配置")
            if target.get("release"):
                incoming = target["release"]
                if self.current is None or self.current[0]["id"] != incoming["id"]:
                    self.accept({**incoming, "environment": target.get("environment")})
            if self.current is None:
                raise ValueError("Admin没有可加载的已发布配置")
            self.last_error = None
        except Exception as error:  # noqa: BLE001 - keep the last successful configuration
            self.last_error = (
                str(error)[:200]
                if isinstance(error, ValueError)
                else type(error).__name__
            )
        if not acknowledge:
            return
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

    def restore_cache(self):
        if self.cache.is_file():
            try:
                self.accept(json.loads(self.cache.read_text()))
            except Exception:  # noqa: BLE001 - invalid cache must not prevent startup
                self.last_error = "invalid_cached_release"

    def start(self, *, block=True):
        self.restore_cache()
        if block:
            self.tick()

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


def configured_runtime():
    # APP_ENV never disables Admin implicitly. CLI evaluations force snapshot mode.
    mode = os.getenv("AGENT_CONFIG_SOURCE", "admin" if os.getenv("APP_ENV") in {"production", "prod"} else "snapshot")
    if mode not in {"admin", "snapshot"}:
        raise ValueError("AGENT_CONFIG_SOURCE只允许admin或snapshot")
    if mode == "snapshot":
        return
    source = os.getenv("AGENT_CONFIG_SOURCE_URL", "")
    token = os.getenv("AGENT_ADMIN_INTERNAL_TOKEN", "")
    if not source or len(token) < 32:
        raise ValueError("Admin配置模式必须提供内部发布地址和至少32字符通信密钥")
    return ReleaseRuntime(source, token, Path(os.getenv("AGENT_CONFIG_CACHE", "var/admin/last-good.json")),
                             expected_environment="prod" if os.getenv("APP_ENV") in {"production", "prod"} else "test")



def start_runtime(*, block=True):
    global runtime
    runtime = configured_runtime()
    if runtime is not None:
        runtime.start(block=block)


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
        from app.agent_specs.definitions import base_definitions, use_definitions
        with use_definitions(base_definitions()):
            yield


def configured_call(function):
    """Pin an entire application call, including context building and retries."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with pin_release():
            return function(*args, **kwargs)

    return wrapped


def register_worker_lifecycle():
    from celery.signals import worker_process_init, worker_process_shutdown

    def start(**kwargs):
        start_runtime(block=False)

    def stop(**kwargs):
        close_runtime()

    worker_process_init.connect(start, weak=False, dispatch_uid="agent-config-start")
    worker_process_shutdown.connect(stop, weak=False, dispatch_uid="agent-config-stop")
