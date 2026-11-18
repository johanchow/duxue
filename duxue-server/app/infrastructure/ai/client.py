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
    kwargs: dict = {"http_client": httpx.Client(trust_env=False)}
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
