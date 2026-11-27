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
        if self.expected_environment == "prod":
            from app.application.workflows.image_review import require_configuration
            require_configuration(release["bundle"])
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
        snapshot.catalog.activation = {k: release[k] for k in ("id", "generation", "activated_at") if k in release}
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
                if (self.current is None or self.current[0]["id"] != incoming["id"]
                        or self.current[0].get("generation") != target.get("generation")):
                    self.accept({**incoming, "environment": target.get("environment"),
                                 "generation": target.get("generation"), "activated_at": target.get("activated_at")})
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
            raise AgentConfigurationUnavailable("No compatible Admin configuration is loaded")
        with use_definitions(current[1].catalog):
            from opentelemetry import trace

            span = trace.get_current_span()
            prefix = "agent.draft" if current[0].get("kind") == "draft" else "agent.release"
            span.set_attribute(prefix + ".id", current[0]["id"])
            span.set_attribute(prefix + ".digest", current[1].digest)
            if prefix == "agent.draft":
                span.set_attribute("agent.draft.revision", current[0]["revision"])
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


class WorkingDraftRuntime(ReleaseRuntime):
    """Local App preview of Admin test data. Keep the pinned bundle in memory only."""

    def restore_cache(self):
        pass

    def tick(self, *, acknowledge=False):
        headers = {"Authorization": "Bearer " + self.token}
        try:
            response = httpx.get(self.source + "/working-draft", headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data["environment"] != "test":
                raise ValueError("草稿环境不匹配")
            draft = data["draft"]
            if draft is None:
                response = httpx.get(self.source + "/release", headers=headers, timeout=5)
                response.raise_for_status()
                data = response.json()
                if data["environment"] != "test" or not data.get("release"):
                    raise ValueError("测试 Admin 没有工作草稿或发布")
                record = {**data["release"], "kind": "release", "revision": data["generation"]}
            else:
                record = {**draft, "kind": "draft"}
            if not self.current or any(self.current[0].get(k) != record[k] for k in ("kind", "id", "revision")):
                compiled = compile_bundle(record["bundle"])
                if record["kind"] == "release" and record["digest"] != compiled.digest:
                    raise ValueError("release digest mismatch")
                compiled.catalog.activation = {"id": record["id"], "generation": record["revision"]}
                self.current = (record, compiled)
            self.last_error = None
        except (httpx.HTTPError, KeyError, ValueError) as error:
            self.last_error = type(error).__name__
            self.current = None
            logging.getLogger(__name__).warning(
                "Admin working draft unavailable: %s%s", self.last_error,
                f": {str(error)[:200]}" if isinstance(error, ValueError) else "",
            )


class AgentConfigurationUnavailable(RuntimeError):
    pass


runtime = None


def configured_runtime():
    if os.getenv("AGENT_CONFIG_SOURCE", "admin") != "admin":
        raise ValueError("业务 API/Worker 必须从 Admin 加载配置；文件快照仅用于离线评测")
    source = os.getenv("AGENT_CONFIG_SOURCE_URL", "")
    token = os.getenv("AGENT_ADMIN_INTERNAL_TOKEN", "")
    if not source or len(token) < 32:
        raise ValueError("Admin配置模式必须提供内部发布地址和至少32字符通信密钥")
    environment = "prod" if os.getenv("APP_ENV") in {"production", "prod"} else "test"
    channel = os.getenv("AGENT_CONFIG_CHANNEL", "release")
    cache = Path(os.getenv("AGENT_CONFIG_CACHE", "var/admin/last-good.json"))
    if channel == "working-draft":
        from urllib.parse import urlsplit
        if environment != "test" or urlsplit(source).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("工作草稿仅允许本机连接测试 Admin")
        return WorkingDraftRuntime(source, token, cache, expected_environment="test")
    if channel != "release":
        raise ValueError("未知 Admin 配置渠道")
    return ReleaseRuntime(source, token, cache, expected_environment=environment)



def start_runtime(*, block=True):
    global runtime
    runtime = configured_runtime()
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
