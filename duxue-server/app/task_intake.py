"""LLM-backed, non-persistent conversational task extraction."""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .config import settings
from .observability import model_call_span
from .schemas import TaskCandidate, TaskIntakeRequest
from .storage import storage


class TaskIntakeError(RuntimeError):
    pass


class TaskIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    tasks: list[TaskCandidate] = Field(default_factory=list, max_length=30)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False


def _data_url(key: str) -> str:
    raw = storage.read_bytes(key)
    suffix = Path(key).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".heic": "image/heic"}.get(suffix, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _prompt(wards: list[dict], request: TaskIntakeRequest) -> str:
    return f"""你是读学的任务整理助手。今天是 {date.today().isoformat()}。
你只能把任务分配给以下监护人已绑定的孩子（只能使用其 id，绝不能创造、猜测或使用其他 id）：
{json.dumps(wards, ensure_ascii=False)}

当前候选任务（它们尚未保存，可按本轮对话修改）：
{json.dumps([task.model_dump(mode='json') for task in request.tasks], ensure_ascii=False)}

对话历史：
{json.dumps([message.model_dump() for message in request.history], ensure_ascii=False)}

硬规则：
1. 多个孩子时，只要某项任务的归属没有由监护人或图片明确说明，就必须 clarification_required=true、ready_to_confirm=false，并在 questions 中只追问必要的归属问题。绝不默认复制给所有孩子，不依据年级、历史或名字相似性猜测。
2. 不补造作业页码、科目、截止日或优先级；日期含糊时在 assistant_text 中说明并保留为空，只有归属和标题明确才可确认。
3. Guardian 的修正可以引用“第二项”“刚才的任务”；据此更新整个 tasks 清单。
4. 只输出一个 JSON object：assistant_text、tasks、clarification_required、questions、ready_to_confirm。tasks 每项必须是 ward_id、title、details（可为 null）、due_date（YYYY-MM-DD 或 null）。
5. 只有每项都属于白名单且 title 非空，且没有待澄清的归属时 ready_to_confirm 才能为 true。"""


class TaskIntakeService:
    def respond(self, *, wards: list[dict], request: TaskIntakeRequest) -> TaskIntakeResult:
        if not request.content and not request.attachment_keys:
            raise TaskIntakeError("请先输入文字或添加图片")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.dashscope_base_url)
            content: list[dict] = [{"type": "text", "text": _prompt(wards, request) + "\n\n本轮监护人消息：\n" + request.content}]
            content.extend({"type": "image_url", "image_url": {"url": _data_url(key)}} for key in request.attachment_keys)
            with model_call_span(operation="task_intake", model=settings.task_intake_model) as telemetry:
                response = client.chat.completions.create(
                    model=settings.task_intake_model,
                    messages=[{"role": "user", "content": content}],
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_tokens=1600,
                )
                usage = response.usage
                telemetry["provider_request_id"] = getattr(response, "id", None)
                telemetry["tokens_in"] = getattr(usage, "prompt_tokens", None)
                telemetry["tokens_out"] = getattr(usage, "completion_tokens", None)
            raw = response.choices[0].message.content or "{}"
            result = TaskIntakeResult.model_validate_json(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise TaskIntakeError("任务解析结果格式异常，请换一种说法重试") from error
        except Exception as error:
            raise TaskIntakeError("任务解析暂不可用，请稍后重试") from error
        ward_ids = {ward["id"] for ward in wards}
        if any(task.ward_id not in ward_ids for task in result.tasks):
            raise TaskIntakeError("任务解析包含无权访问的孩子，请重新说明归属")
        if result.clarification_required or not result.tasks:
            result.ready_to_confirm = False
        return result
