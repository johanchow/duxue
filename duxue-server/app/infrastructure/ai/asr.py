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

        # Reach DashScope directly. A shell HTTP proxy such as a stopped local
        # proxy on 127.0.0.1 must not fail hold-to-talk.
        connection = await connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {settings.asr_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            proxy=None,
        )
        session = cls(connection)
        await session._send({
            "type": "session.update",
            "session": {"turn_detection": _SERVER_VAD},
        })
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


_SERVER_VAD = {
    "type": "server_vad",
    "threshold": 0.5,
    "silence_duration_ms": 800,
}


class AsrHold:
    """按住说话：识别过程持续给出草稿，松手提交后才给出唯一终稿。

    服务端 VAD 可能在停顿时先结束一段。那段文字先作为草稿转发，
    连接保持到客户端 commit，避免松手前提交整句。
    """

    def __init__(self) -> None:
        self.segments: list[str] = []
        self.live = ""
        self.pending_audio = False
        self.committed = False
        self.finished = False

    def note_audio(self) -> None:
        self.pending_audio = True

    def on_provider(self, event: dict) -> list[dict]:
        if self.finished:
            return []
        kind = event.get("type")
        if kind == "error":
            if self.committed and self._preview():
                return self._emit_final()
            self.finished = True
            return [event]
        if kind == "partial":
            self.live = event.get("text") or ""
            preview = self._preview()
            return [{"type": "partial", "text": preview}] if preview else []
        if kind == "final":
            text = (event.get("text") or "").strip()
            if text:
                self.segments.append(text)
            self.live = ""
            if self.committed:
                return self._emit_final()
            preview = self._preview()
            return [{"type": "partial", "text": preview}] if preview else []
        return []

    def commit(self) -> list[dict]:
        """松手。还有未刷新的音频时先不给终稿，等服务端 commit 的结果。"""
        self.committed = True
        if self.finished or self.pending_audio:
            return []
        return self._emit_final()

    def unfinished_final(self) -> list[dict]:
        if self.finished:
            return []
        self.committed = True
        return self._emit_final()

    def _emit_final(self) -> list[dict]:
        self.finished = True
        return [{"type": "final", "text": self._transcript() or self.live.strip()}]

    def _transcript(self) -> str:
        return "".join(self.segments)

    def _preview(self) -> str:
        if self.live:
            return "".join([*self.segments, self.live])
        return self._transcript()


async def forward_asr_events(session: DashscopeRealtimeAsr, send, hold: AsrHold | None = None) -> str:
    """Forward provider events without retaining raw audio or transcripts."""
    hold = hold or AsrHold()
    async for event in session.events():
        for item in hold.on_provider(event):
            await send(item)
            if item["type"] in {"final", "error"}:
                return item["type"]
    if hold.committed and not hold.finished:
        for item in hold.unfinished_final():
            await send(item)
        return "final"
    return "error"
