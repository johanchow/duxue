from __future__ import annotations

from dataclasses import replace

import pytest

from app.bootstrap.settings import settings
from app.infrastructure.ai import asr as asr_module
from app.infrastructure.ai.asr import DashscopeRealtimeAsr


class _Connection:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_dashscope_asr_connects_directly_and_ignores_ambient_proxy(monkeypatch):
    captured: dict = {}

    async def connect(url, **kwargs):
        captured["url"] = url
        captured["proxy"] = kwargs.get("proxy", "missing")
        return _Connection()

    monkeypatch.setattr(
        asr_module,
        "settings",
        replace(
            settings,
            asr_api_key="test-key",
            asr_websocket_url="wss://asr.example/realtime",
        ),
    )
    monkeypatch.setattr("websockets.asyncio.client.connect", connect)

    session = await DashscopeRealtimeAsr.connect()

    assert captured["url"] == "wss://asr.example/realtime"
    assert captured["proxy"] is None
    assert session._connection.sent
