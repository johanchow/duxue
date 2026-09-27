"""Shared DashScope client.

Model calls connect directly. A shell HTTP proxy, including a stopped local
proxy, must not fail plan intake or other provider requests.
"""
from __future__ import annotations

import httpx
from openai import OpenAI

from app.bootstrap.settings import settings


def dashscope_client(*, timeout: float | None = None) -> OpenAI:
    kwargs: dict = {"http_client": httpx.Client(trust_env=False)}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        **kwargs,
    )
