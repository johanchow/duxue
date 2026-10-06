from __future__ import annotations

from dataclasses import replace

import json

import pytest

from app.bootstrap.settings import settings
from app.infrastructure.ai import asr as asr_module
from app.infrastructure.ai.asr import AsrHold, DashscopeRealtimeAsr, forward_asr_events


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
    session_update = json.loads(session._connection.sent[0])
    assert session_update["session"]["turn_detection"]["type"] == "server_vad"


def test_hold_keeps_provider_final_as_draft_until_the_finger_releases():
    hold = AsrHold()
    assert hold.on_provider({"type": "partial", "text": "安排明天的数"}) == [
        {"type": "partial", "text": "安排明天的数"}
    ]
    assert hold.on_provider({"type": "final", "text": "安排明天的数学作业"}) == [
        {"type": "partial", "text": "安排明天的数学作业"}
    ]
    assert hold.commit() == [{"type": "final", "text": "安排明天的数学作业"}]


def test_hold_joins_a_later_phrase_after_a_pause():
    hold = AsrHold()
    hold.on_provider({"type": "final", "text": "先读课文"})
    hold.note_audio()
    assert hold.commit() == []
    assert hold.on_provider({"type": "final", "text": "再做数学"}) == [
        {"type": "final", "text": "先读课文再做数学"}
    ]


def test_hold_uses_the_draft_when_commit_hits_a_provider_error():
    hold = AsrHold()
    hold.on_provider({"type": "partial", "text": "数学"})
    hold.note_audio()
    assert hold.commit() == []
    assert hold.on_provider({"type": "error", "message": "empty buffer"}) == [
        {"type": "final", "text": "数学"}
    ]


class _Events:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def events(self):
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_forward_does_not_finish_the_turn_before_commit():
    sent: list[dict] = []
    hold = AsrHold()

    async def send(event: dict) -> None:
        sent.append(event)

    outcome = await forward_asr_events(
        _Events([
            {"type": "partial", "text": "安排"},
            {"type": "final", "text": "安排数学"},
        ]),
        send,
        hold,
    )

    assert outcome == "error"
    assert sent == [
        {"type": "partial", "text": "安排"},
        {"type": "partial", "text": "安排数学"},
    ]
    assert hold.commit() == [{"type": "final", "text": "安排数学"}]
