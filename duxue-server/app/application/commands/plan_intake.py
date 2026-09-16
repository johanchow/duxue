"""Ward-owned, non-persistent daily plan draft extraction."""
from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from app.bootstrap.settings import settings
from app.infrastructure.observability.telemetry import model_call_span

from .task_intake import TaskIntakeError, _data_url


class PlanIntakeItem(BaseModel):
    assignment_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    details: str | None = Field(default=None, max_length=4000)
    planned_minutes: int | None = Field(default=None, ge=1, le=480)
    new_task: bool = False


class PlanIntakeInput(BaseModel):
    """Internal Planning workflow input; it is deliberately independent of HTTP."""

    content: str = Field(default="", max_length=4000)
    draft_items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)


class PlanIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False


def _prompt(ward: dict, tasks: list[dict], request: PlanIntakeInput) -> str:
    return f"""你是读学的当天计划整理助手。今天是 {date.today().isoformat()}。
你只能为当前学生生成今天的草稿，绝不能安排其他人或其他日期。
当前学生：{json.dumps(ward, ensure_ascii=False)}
当前未完成任务池：{json.dumps(tasks, ensure_ascii=False)}
当前尚未确认的草稿：{json.dumps([item.model_dump() for item in request.draft_items], ensure_ascii=False)}

硬规则：
1. 根据本轮学生输入或图片，保留、增加、删除或调整今天的草稿任务；不要编造作业内容、页码或截止日。
2. 引用任务池已有任务时必须使用其 assignment_id 且 new_task=false；学生新提出的任务使用 new_task=true 且 assignment_id=null。
3. 每项必须有 title。planned_minutes 只有学生明确说出预计时长时才能填写（1 到 480）；绝不猜测或默认任何时长。缺少预计时长时保持 planned_minutes=null，clarification_required=true、ready_to_confirm=false，并在 questions 中只追问预计时长。
4. 只有草稿至少有一项、每项都有明确预计时长且信息足够明确时 ready_to_confirm=true。
5. 只输出 JSON object：assistant_text、items、clarification_required、questions、ready_to_confirm。"""


def require_missing_duration_clarification(result: PlanIntakeResult) -> PlanIntakeResult:
    """Turn an omitted duration into an explicit Ward-facing clarification."""
    titles = [item.title for item in result.items if item.planned_minutes is None]
    if not titles:
        return result
    task_names = "、".join(f"“{title}”" for title in titles)
    question = f"{task_names} 预计需要多长时间？"
    result.assistant_text = f"还需要补充预计时长：{question}"
    result.clarification_required = True
    result.questions = [question]
    result.ready_to_confirm = False
    return result


class PlanIntakeService:
    def respond(self, *, ward: dict, tasks: list[dict], request: PlanIntakeInput) -> PlanIntakeResult:
        if not request.content and not request.attachment_keys:
            raise TaskIntakeError("请先输入文字、说话或添加图片")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.dashscope_base_url)
            content: list[dict] = [{"type": "text", "text": _prompt(ward, tasks, request) + "\n\n本轮学生消息：\n" + request.content}]
            content.extend({"type": "image_url", "image_url": {"url": _data_url(key)}} for key in request.attachment_keys)
            with model_call_span(operation="plan_intake", model=settings.task_intake_model) as telemetry:
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
            result = PlanIntakeResult.model_validate_json(response.choices[0].message.content or "{}")
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise TaskIntakeError("计划草稿格式异常，请换一种说法重试") from error
        except Exception as error:
            raise TaskIntakeError("计划整理暂不可用，请稍后重试") from error
        known_ids = {task["id"] for task in tasks}
        if any(item.assignment_id not in known_ids for item in result.items if item.assignment_id):
            raise TaskIntakeError("计划草稿包含无效任务，请重新说明")
        if any(item.new_task == (item.assignment_id is not None) for item in result.items):
            raise TaskIntakeError("计划草稿中的任务来源不正确，请重新说明")
        require_missing_duration_clarification(result)
        if result.clarification_required or not result.items:
            result.ready_to_confirm = False
        return result
