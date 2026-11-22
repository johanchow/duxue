"""Shared DashScope client.

Model calls connect directly. A shell HTTP proxy, including a stopped local
proxy, must not fail plan intake or other provider requests.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

import httpx
from openai import OpenAI

from app.bootstrap.settings import settings
from app.infrastructure.ai.errors import ModelTimeBudgetExceeded

_model_deadline: ContextVar[float | None] = ContextVar("model_deadline", default=None)


_transport: ContextVar[tuple[dict, float] | None] = ContextVar("model_transport", default=None)


@contextmanager
def observe_transport(observation: dict):
    token = _transport.set((observation, monotonic()))
    try:
        yield
    finally:
        _transport.reset(token)


def _request_started(request: httpx.Request) -> None:
    active = _transport.get()
    if active is None:
        return
    observation, _ = active
    observation["http_attempts"] = observation.get("http_attempts", 0) + 1
    observation["read_timeout_seconds"] = request.extensions.get("timeout", {}).get("read")
    deadline = _model_deadline.get()
    if deadline is not None:
        observation["remaining_budget_ms"] = max(0, round((deadline - monotonic()) * 1000))


def _headers_received(response: httpx.Response) -> None:
    active = _transport.get()
    if active is not None:
        observation, started = active
        observation["response_headers_ms"] = round((monotonic() - started) * 1000)


@contextmanager
def model_time_budget(seconds: float):
    token = _model_deadline.set(monotonic() + seconds)
    try:
        yield
    finally:
        _model_deadline.reset(token)


def remaining_model_time() -> float | None:
    deadline = _model_deadline.get()
    if deadline is None:
        return None
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ModelTimeBudgetExceeded("model_time_budget_exhausted")
    return remaining


def dashscope_client(*, timeout: float | None = None) -> OpenAI:
    remaining = remaining_model_time()
    kwargs: dict = {"http_client": httpx.Client(trust_env=False, event_hooks={
        "request": [_request_started], "response": [_headers_received],
    })}
    if remaining is not None:
        timeout = min(timeout or remaining, remaining)
        kwargs["max_retries"] = 0
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        **kwargs,
    )
