"""Ward-owned, non-persistent daily plan draft extraction."""
from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from app.bootstrap.settings import settings
from app.infrastructure.observability.telemetry import model_call_span

from .task_intake import TaskIntakeError, _data_url


class PlanIntakeItem(BaseModel):
    # Model output is a human-visible reference, never authority to choose a
    # database identity.  assignment_id remains only for the legacy direct
    # planning_items adapter.
    task_reference: str | None = Field(default=None, max_length=300)
    assignment_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    details: str | None = Field(default=None, max_length=4000)
    planned_minutes: int | None = Field(default=None, ge=1, le=480)
    start_at: str | None = None
    after_task_reference: str | None = Field(default=None, max_length=300)
    before_task_reference: str | None = Field(default=None, max_length=300)
    after_assignment_id: str | None = None  # legacy direct adapter only
    before_assignment_id: str | None = None  # legacy direct adapter only
    new_task: bool = False


class PlanIntakeInput(BaseModel):
    """Internal Planning workflow input; it is deliberately independent of HTTP."""

    content: str = Field(default="", max_length=4000)
    draft_items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    clarification_slots: list[dict] = Field(default_factory=list, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)


class PlanIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False
    slot_updates: list[dict] = Field(default_factory=list, max_length=30)


def _prompt(ward: dict, tasks: list[dict], request: PlanIntakeInput) -> str:
    draft_items = []
    for item in request.draft_items:
        projected = item.model_dump()
        for identity_field in ("assignment_id", "after_assignment_id", "before_assignment_id"):
            projected.pop(identity_field, None)
        draft_items.append(projected)
    return f"""你是读学的当天计划整理助手。今天是 {date.today().isoformat()}。
你只能为当前学生生成今天的草稿，绝不能安排其他人或其他日期。
当前学生：{json.dumps(ward, ensure_ascii=False)}
当前未完成任务池：{json.dumps(tasks, ensure_ascii=False)}
当前尚未确认的草稿：{json.dumps(draft_items, ensure_ascii=False)}
当前待补槽位：{json.dumps(request.clarification_slots, ensure_ascii=False)}

硬规则：
1. 根据本轮学生输入或图片，保留、增加、删除或调整今天的草稿任务；不要编造作业内容、页码或截止日。
2. 绝不输出 assignment_id、after_assignment_id、before_assignment_id，也不要决定 new_task。引用任务池已有任务时，必须从当前任务池复制该任务的完整标题到 task_reference 与 title；即使本轮只是修改开始时间，也绝不能把已有任务改写成新任务。只有任务池中没有对应任务时才填写新 title 且 task_reference=null。服务端会负责绑定真实 Task ID。
3. 你负责理解自然语言：区分钟表时间（如“十九点三十分”）与持续时长（如“预计三十分钟”）。可同时输出 slot_updates 和 items 中的排程 patch。slot_updates 只能使用当前待补槽位中的 slot_id，形如 {{slot_id, value:"30分钟"}}；钟表时间绝不能填入 planned_minutes。每项必须有 title。planned_minutes 只有学生明确说出预计时长时才能填写（1 到 480）；绝不猜测或默认任何时长。学生明确给出开始时间时才填写 ISO 8601 start_at；绝不猜测开始时间。表达“在数学之后/英语之前”时填写 after_task_reference/before_task_reference（任务名称）。
4. 一个开始时间必须属于一个明确任务。任务池有多个候选而学生只说“18点开始”时，不得给多个 item 填同一个 start_at；保持时间为空并追问先做哪一项。
5. 只有草稿至少有一项、每项都有明确预计时长和可确定时间槽且信息足够明确时 ready_to_confirm=true。
6. 只输出 JSON object：assistant_text、items、slot_updates、clarification_required、questions、ready_to_confirm。"""


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
        if any(item.assignment_id or item.after_assignment_id or item.before_assignment_id for item in result.items):
            raise TaskIntakeError("计划草稿不能由模型指定任务 ID，请重新说明")
        require_missing_duration_clarification(result)
        if result.clarification_required or not result.items:
            result.ready_to_confirm = False
        return result
