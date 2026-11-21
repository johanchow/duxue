"""DashScope duplex speech tasks (binary PCM input / MP3 output)."""

from __future__ import annotations

import asyncio
import json
import re
from uuid import uuid4

from websockets.asyncio.client import connect

from app.bootstrap.settings import settings


class SpeechTask:
    def __init__(self, connection):
        self.connection = connection
        self.id = uuid4().hex

    @classmethod
    async def open(cls, *, task, function, model, parameters):
        if not settings.asr_api_key:
            raise ValueError("speech credentials unavailable")
        host = (
            f"{settings.asr_workspace_id}.cn-beijing.maas.aliyuncs.com"
            if settings.asr_workspace_id
            else "dashscope.aliyuncs.com"
        )
        connection = await connect(
            settings.speech_task_url or f"wss://{host}/api-ws/v1/inference",
            additional_headers={"Authorization": f"Bearer {settings.asr_api_key}"},
            proxy=None,
            open_timeout=5,
            close_timeout=1,
        )
        session = cls(connection)
        try:
            await session.command(
                "run-task",
                task_group="audio",
                task=task,
                function=function,
                model=model,
                parameters=parameters,
            )
            reply = json.loads(await asyncio.wait_for(connection.recv(), 8))
            if reply["header"]["event"] != "task-started":
                raise RuntimeError(
                    "speech task rejected: "
                    + str(reply["header"].get("error_code", "unknown"))
                )
        except BaseException:
            await connection.close()
            raise
        return session

    async def command(self, action, **payload):
        await self.connection.send(
            json.dumps(
                {
                    "header": {
                        "action": action,
                        "task_id": self.id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}, **payload},
                }
            )
        )

    async def close(self):
        await self.connection.close()


# Same four formula delimiters as the Ward Markdown renderer.
MATH_DELIMITERS = re.compile(
    r"\$\$.+?\$\$|\\\(.+?\\\)|\\\[.+?\\\]|(?<!\$)\$(?!\s)[^\n$]+?(?<!\s)\$(?![\d$])",
    re.DOTALL,
)


def distinguish_negative_powers(text: str) -> str:
    """Spell the scope of unary minus for a complete, signed numeric power."""

    def spoken(match):
        formula = match.group()
        border = 1 if formula.startswith("$") and not formula.startswith("$$") else 2
        power = re.fullmatch(
            r"(?:(?:-\s*(\d+(?:\.\d+)?))|(?:\(\s*-\s*(\d+(?:\.\d+)?)\s*\)))\s*\^\s*(?:\{(\d+)\}|(\d+))",
            formula[border:-border].strip(),
        )
        if not power:
            return formula
        unsigned, negative_base, braced, plain = power.groups()
        exponent = braced or plain
        raised = {"2": "平方", "3": "立方"}.get(exponent, f"{exponent}次方")
        if negative_base:
            return f"负{negative_base}整体的{raised}"
        return f"{unsigned}的{raised}的相反数"

    return MATH_DELIMITERS.sub(spoken, text)


async def tutor_audio_frames(text: str):
    text = distinguish_negative_powers(text)
    deadline = asyncio.get_running_loop().time() + 25
    async with asyncio.timeout_at(deadline):
        parameters = {
            "text_type": "PlainText",
            "voice": settings.tutor_tts_voice,
            "format": "mp3",
            "sample_rate": 22050,
            "enable_markdown_filter": True,
            "instruction": "像耐心的一对一老师，语速自然。条件和关键词轻轻重读，提问前稍停。忠实朗读原文。",
        }
        model = settings.tutor_tts_model
        if MATH_DELIMITERS.search(text):
            model = "cosyvoice-v3-flash"
            parameters.update(voice="longanyang")
            parameters.pop("instruction")
        task = await SpeechTask.open(
            task="tts", function="SpeechSynthesizer", model=model, parameters=parameters
        )
    try:
        async with asyncio.timeout_at(deadline):
            await task.command("continue-task", input={"text": text})
            await task.command("finish-task")
        has_audio = False
        frames = aiter(task.connection)
        while True:
            async with asyncio.timeout_at(deadline):
                frame = await anext(frames, None)
            if isinstance(frame, bytes):
                if frame:
                    has_audio = True
                    yield frame
                continue
            if frame is None:
                break
            event = json.loads(frame)["header"]["event"]
            if event == "task-finished" and has_audio:
                return
            if event == "task-failed":
                break
        raise RuntimeError("incomplete speech synthesis")
    finally:
        await task.close()


async def tutor_audio(text: str) -> bytes:
    return b"".join([chunk async for chunk in tutor_audio_frames(text)])
