"""LLM-backed, non-persistent conversational task extraction."""
from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from app.agent_specs.contexts import build_context
from app.api.schemas import TaskCandidate, TaskIntakeRequest
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.storage.object_storage import storage


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
    from app.infrastructure.ai.prompts import PROMPTS, DynamicPrompt

    prompt = PROMPTS["task.intake.prompt.v2"]
    assert isinstance(prompt, DynamicPrompt)
    return prompt.render({
        "today": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "authorized_wards": wards,
        "candidate_tasks": [task.model_dump(mode="json") for task in request.tasks],
        "conversation_history": [message.model_dump() for message in request.history],
    })


class TaskIntakeService:
    def respond(self, *, wards: list[dict], request: TaskIntakeRequest) -> TaskIntakeResult:
        if not request.content and not request.attachment_keys:
            raise TaskIntakeError("请先输入文字或添加图片")
        try:
            content = build_context("task.intake", wards=wards, request=request)
            from app.agent_specs.catalog import load_catalog
            from app.agent_specs.runtime import execute_workflow
            catalog = load_catalog()
            state = execute_workflow(
                catalog.spec("task-intake"),
                handlers={"task.intake": lambda _state: components.invoke_agent_component(
                    spec=catalog.component("task-intake", "run"), user=content,
                )},
            )
            payload = state["results"]["task-intake.run"].unwrap()
            result = TaskIntakeResult.model_validate(payload)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise TaskIntakeError("任务解析结果格式异常，请换一种说法重试") from error
        except ModelGatewayError as error:
            if str(error) == "invalid_model_candidate":
                raise TaskIntakeError("任务解析结果格式异常，请换一种说法重试") from error
            raise TaskIntakeError("任务解析暂不可用，请稍后重试") from error
        except Exception as error:
            raise TaskIntakeError("任务解析暂不可用，请稍后重试") from error
        ward_ids = {ward["id"] for ward in wards}
        if any(task.ward_id not in ward_ids for task in result.tasks):
            raise TaskIntakeError("任务解析包含无权访问的孩子，请重新说明归属")
        if result.clarification_required or not result.tasks:
            result.ready_to_confirm = False
        return result
