"""Server-side relay for DashScope real-time ASR.

The mobile client only ever talks to this module through our authenticated
WebSocket endpoint.  DashScope credentials therefore remain server-side.
"""
from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator

from app.bootstrap.settings import settings


class AsrConfigurationError(RuntimeError):
    pass


class DashscopeRealtimeAsr:
    """Minimal Manual-mode client for qwen3-asr-flash-realtime."""

    def __init__(self, connection) -> None:
        self._connection = connection

    @classmethod
    async def connect(cls) -> "DashscopeRealtimeAsr":
        if not settings.asr_api_key:
            raise AsrConfigurationError("ASR_API_KEY is not configured")
        url = settings.asr_websocket_url
        if not url and settings.asr_workspace_id:
            url = (
                f"wss://{settings.asr_workspace_id}.cn-beijing.maas.aliyuncs.com/"
                f"api-ws/v1/realtime?model={settings.asr_model}"
            )
        if not url:
            raise AsrConfigurationError("ASR_WORKSPACE_ID or ASR_WEBSOCKET_URL is required")

        from websockets.asyncio.client import connect

        connection = await connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {settings.asr_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
        )
        session = cls(connection)
        await session._send({"type": "session.update", "session": {"turn_detection": None}})
        return session

    async def _send(self, event: dict) -> None:
        await self._connection.send(json.dumps(event, separators=(",", ":")))

    async def send_audio(self, chunk: bytes) -> None:
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(chunk).decode(),
        })

    async def commit(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"})

    async def finish(self) -> None:
        await self._send({"type": "session.finish"})

    async def close(self) -> None:
        await self._connection.close()

    async def events(self) -> AsyncIterator[dict[str, str]]:
        async for raw in self._connection:
            payload = json.loads(raw)
            event_type = payload.get("type")
            if event_type == "conversation.item.input_audio_transcription.text":
                yield {"type": "partial", "text": payload.get("text", "") + payload.get("stash", "")}
            elif event_type == "conversation.item.input_audio_transcription.completed":
                yield {"type": "final", "text": payload.get("transcript", "")}
            elif event_type == "error":
                yield {"type": "error", "message": payload.get("error", {}).get("message", "ASR provider error")}


async def forward_asr_events(session: DashscopeRealtimeAsr, send) -> str:
    """Forward provider events without retaining raw audio or transcripts."""
    async for event in session.events():
        await send(event)
        if event["type"] in {"final", "error"}:
            return event["type"]
