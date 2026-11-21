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
            asr_model="qwen3-asr-flash-realtime",
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


def test_hold_reports_provider_failure_instead_of_sending_an_unfinished_draft():
    hold = AsrHold()
    hold.on_provider({"type": "partial", "text": "数学"})
    hold.note_audio()
    assert hold.commit() == []
    assert hold.on_provider({"type": "error", "message": "empty buffer"}) == [
        {"type": "error", "message": "empty buffer"}
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


@pytest.mark.asyncio
async def test_message_asr_revisions_are_scoped_to_sentence_until_task_finished():
    from types import SimpleNamespace
    from app.infrastructure.ai.asr import MessageAsr

    async def frames():
        for number, text, final in [(1, "负", False), (1, "负三", True),
                                    (2, "不", False), (2, "不对，是三", True)]:
            yield json.dumps({"header": {"event": "result-generated"}, "payload": {
                "output": {"sentence": {"sentence_id": number, "text": text, "sentence_end": final}}}})
        yield json.dumps({"header": {"event": "task-finished"}})

    session = MessageAsr(SimpleNamespace(connection=frames()))
    events = [event async for event in session.events()]
    assert events[-1] == {"type": "final", "text": "负三不对，是三"}
    assert all(event["type"] == "partial" for event in events[:-1])


def test_incomplete_tail_after_committed_sentence_is_not_sent_as_final():
    hold = AsrHold()
    hold.on_provider({"type": "final", "text": "我觉得是负三"})
    hold.note_audio()
    hold.on_provider({"type": "partial", "text": "不对"})
    assert hold.commit() == []
    assert hold.unfinished_final()[0]["type"] == "error"


def test_math_reading_preserves_the_scope_of_unary_minus():
    from app.infrastructure.ai.speech_task import distinguish_negative_powers
    assert distinguish_negative_powers(r"比较 $-3^2$ 和 \((-3)^{2}\)。") == "比较 3的平方的相反数 和 负3整体的平方。"
    assert distinguish_negative_powers(r"\[x-3^2\]") == r"\[x-3^2\]"


@pytest.mark.asyncio
async def test_display_session_streams_the_same_chunks_and_handles_an_optional_failure(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.infrastructure.ai.asr import DisplayTranscript, MessageAsr

    committed = asyncio.Event()
    class Session:
        send_audio = AsyncMock()
        close = AsyncMock()

        async def commit(self):
            committed.set()

        async def events(self):
            await committed.wait()
            yield {"type": "partial", "text": "为什么"}
            yield {"type": "final", "text": "为什么要通分？"}

    session = Session()
    monkeypatch.setattr(MessageAsr, "connect", AsyncMock(return_value=session))
    display = DisplayTranscript()
    display.append(b"pcm")
    display.commit()
    assert await display.result() == "为什么要通分？"
    session.send_audio.assert_awaited_once_with(b"pcm")
    await display.close()
    session.close.assert_awaited_once()

    monkeypatch.setattr(MessageAsr, "connect", AsyncMock(side_effect=OSError()))
    display = DisplayTranscript()
    display.commit()
    assert await display.result() is None
    await display.close()
