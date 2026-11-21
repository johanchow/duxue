import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.ai.speech_task import SpeechTask, tutor_audio


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_model"),
    [
        ("**先看已知条件**。", "qwen-audio-3.1-tts-flash"),
        (r"比较 $\frac{1}{3}$ 和 $\frac{1}{6}$。", "cosyvoice-v3-flash"),
    ],
)
async def test_tutor_reads_confirmed_text_and_returns_complete_audio(
    monkeypatch, text, expected_model
):
    async def frames():
        yield b"one"
        yield b"two"
        yield json.dumps({"header": {"event": "task-finished"}})

    task = SimpleNamespace(connection=frames(), command=AsyncMock(), close=AsyncMock())
    opener = AsyncMock(return_value=task)
    monkeypatch.setattr(SpeechTask, "open", opener)
    assert await tutor_audio(text) == b"onetwo"
    assert opener.await_args.kwargs["model"] == expected_model
    assert task.command.await_args_list[0].kwargs == {"input": {"text": text}}
    task.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_synthesis_failure_discards_partial_audio(monkeypatch):
    async def frames():
        yield b"unfinished"
        yield json.dumps({"header": {"event": "task-failed"}})

    task = SimpleNamespace(connection=frames(), command=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(SpeechTask, "open", AsyncMock(return_value=task))
    with pytest.raises(RuntimeError, match="incomplete"):
        await tutor_audio("先看条件。")
    task.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_audio_stream_delivers_first_frame_and_closes_on_stop(monkeypatch):
    from app.infrastructure.ai.speech_task import tutor_audio_frames

    async def frames():
        yield b"first"
        raise AssertionError("playback stopped before requesting more")

    task = SimpleNamespace(connection=frames(), command=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(SpeechTask, "open", AsyncMock(return_value=task))
    stream = tutor_audio_frames("地球绕太阳公转。")
    assert await anext(stream) == b"first"
    await stream.aclose()
    task.close.assert_awaited_once()
