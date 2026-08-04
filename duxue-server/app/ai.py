from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

from .config import settings
from .models import Frame
from .storage import storage


STRUCTURED_PROMPT = """这张图片来自学生侧后方约45度且略高于头顶的摄像头。请仅依据可见的手部、桌面、头部朝向和身体姿态，用合法 JSON 描述行为，不要输出其他文字，也不要依赖正脸、眼睛或表情。输出字段必须是 hand_action、desk_objects、head_orientation、body_pos、seat_status、motion_state、desc_summary。"""


def _image_data(frame: Frame) -> str:
    raw = storage.read_bytes(frame.oss_key)
    suffix = Path(frame.oss_key).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _request(frame: Frame, extra_prompt: str = "") -> dict:
    return {
        "custom_id": frame.id, "method": "POST", "url": "/v1/chat/completions",
        "body": {"model": settings.vlm_model, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": _image_data(frame)}},
            {"type": "text", "text": STRUCTURED_PROMPT + ("\n额外观察：" + extra_prompt if extra_prompt else "")},
        ]}], "max_tokens": 300, "temperature": 0},
    }


class DashscopeInference:
    """OpenAI-compatible Batch client; imports the SDK only in production calls."""

    def __init__(self):
        if not settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required")
        from openai import OpenAI
        self.client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.dashscope_base_url)

    def submit(self, frames: list[Frame], prompts: dict[str, str]) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as handle:
            path = Path(handle.name)
            for frame in frames:
                handle.write(json.dumps(_request(frame, prompts.get(frame.ward_id, "")), ensure_ascii=False) + "\n")
        try:
            uploaded = self.client.files.create(file=path, purpose="batch")
            batch = self.client.batches.create(input_file_id=uploaded.id, endpoint="/v1/chat/completions", completion_window=settings.batch_completion_window, metadata={"ds_name": f"duxue-{frames[0].captured_at.date()}"})
            return batch.id
        finally:
            path.unlink(missing_ok=True)

    def retrieve(self, batch_id: str) -> tuple[str, dict[str, dict]]:
        batch = self.client.batches.retrieve(batch_id)
        if batch.status != "completed":
            return batch.status, {}
        content = self.client.files.content(batch.output_file_id).text
        results: dict[str, dict] = {}
        for line in content.splitlines():
            row = json.loads(line)
            if row.get("response", {}).get("status_code") != 200:
                continue
            message = row["response"]["body"]["choices"][0]["message"]["content"]
            message = message.strip().removeprefix("```json").removesuffix("```").strip()
            results[row["custom_id"]] = json.loads(message)
        return "completed", results

    def realtime(self, frame: Frame, extra_prompt: str = "") -> dict:
        body = _request(frame, extra_prompt)["body"]
        response = self.client.chat.completions.create(**body)
        content = response.choices[0].message.content.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(content)
