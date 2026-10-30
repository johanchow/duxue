"""Ward-owned, non-persistent daily plan draft extraction."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from app.agent_specs.contexts import build_context
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.utterance_window import WINDOW_RULE, window_text
from app.infrastructure.observability.telemetry import record_plan_intake_structure

from .task_intake import TaskIntakeError


class PlanIntakeItem(BaseModel):
    # Model output is a human-visible reference, never authority to choose a
    # database identity.  assignment_id remains only for the legacy direct
    # planning_items adapter.
    task_reference: str | None = Field(default=None, max_length=300)
    assignment_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    details: str | None = Field(default=None, max_length=4000)
    planned_minutes: int | None = Field(default=None, ge=1, le=480)
    start_at: str | None = None
    after_task_reference: str | None = Field(default=None, max_length=300)
    before_task_reference: str | None = Field(default=None, max_length=300)
    after_assignment_id: str | None = None  # legacy direct adapter only
    before_assignment_id: str | None = None  # legacy direct adapter only
    new_task: bool = False


class PlanningOperation(BaseModel):
    kind: Literal["create", "update", "schedule", "defer", "delete"]
    references: list[str] = Field(default_factory=list, max_length=30)
    title: str | None = Field(default=None, max_length=300)
    planned_minutes: int | None = Field(default=None, ge=1, le=480)
    start_at: str | None = None
    after_task_reference: str | None = None
    before_task_reference: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class PlanIntakeInput(BaseModel):
    """Internal Planning workflow input; it is deliberately independent of HTTP."""

    content: str = Field(default="", max_length=4000)
    draft_items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    clarification_slots: list[dict] = Field(default_factory=list, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)
    recent_utterances: list[dict] = Field(default_factory=list, max_length=8)
    omitted_utterance_count: int = Field(default=0, ge=0)
    self_review_aspects: list[dict] = Field(default_factory=list, max_length=4)


class PlanIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False
    slot_updates: list[dict] = Field(default_factory=list, max_length=30)
    operations: list[PlanningOperation] = Field(default_factory=list, max_length=30)


def _prompt(ward: dict, tasks: list[dict], request: PlanIntakeInput) -> str:
    from app.infrastructure.ai.prompts import PROMPTS, DynamicPrompt

    draft_items = []
    for item in request.draft_items:
        projected = item.model_dump()
        for identity_field in ("assignment_id", "after_assignment_id", "before_assignment_id"):
            projected.pop(identity_field, None)
        draft_items.append(projected)
    prompt = PROMPTS["planning.intake.prompt.v3"]
    assert isinstance(prompt, DynamicPrompt)
    return prompt.render({
        "today": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "recent_utterance_block": _recent_utterance_block(request),
        "ward": ward,
        "tasks": tasks,
        "draft_items": draft_items,
        "clarification_slots": request.clarification_slots,
        "self_review_aspects": request.self_review_aspects,
    })

def _recent_utterance_block(request: PlanIntakeInput) -> str:
    rows, current_ids = window_text(request.recent_utterances, len(request.attachment_keys))
    if not rows:
        return _current_image_block(current_ids)
    lines = []
    for item in rows:
        speaker = "学生" if item.get("author") == "ward" else "读学"
        ids = item.get("image_ids") or []
        image = f"（附图片{'、'.join(str(i) for i in ids)}）" if ids else ""
        prefix = "（前段已按预算省略）" if item.get("leading_omitted") else ""
        lines.append(f"{speaker}{image}：{prefix}{item.get('text', '')}")
    omitted = (
        f"更早的 {request.omitted_utterance_count} 条原句已按预算省略，未改写成摘要。\n"
        if request.omitted_utterance_count else
        "这些是同一条对话到上一轮为止的原句，不是改写。\n"
    )
    return (
        WINDOW_RULE + "\n"
        "同一条对话的最近原句（从旧到新）：\n"
        + "\n".join(lines)
        + "\n"
        + omitted
        + "学生确认这些原句里列出的事项要创建时，为其中尚未出现在当前任务池的标题各输出一条 kind=create，并把学生明确说出的时长写入 planned_minutes。不要把「都」改写成任务池里已有的其他任务。原句附带的图片会随后按编号给出，直接看图确认；本轮没有新图片时，以这些原句和它们的附图为准。\n"
        + _current_image_block(current_ids)
        + "\n"
    )


def _current_image_block(current_ids: list[int]) -> str:
    if not current_ids:
        return ""
    return f"本轮学生发来的图片编号：{'、'.join(str(i) for i in current_ids)}。\n"


class PlanIntakeService:
    def respond(self, *, ward: dict, tasks: list[dict], request: PlanIntakeInput) -> PlanIntakeResult:
        if not request.content and not request.attachment_keys:
            raise TaskIntakeError("请先输入文字、说话或添加图片")
        try:
            content = build_context("planning.intake", ward=ward, tasks=tasks, request=request)
            from app.agent_specs.catalog import load_catalog
            payload = components.invoke_agent_component(
                spec=load_catalog().component("planning", "plan_intake"), user=content,
            ).unwrap()
            result = PlanIntakeResult.model_validate(payload)
            record_plan_intake_structure(
                has_image=bool(request.attachment_keys),
                operation_count=len(result.operations),
                slot_update_count=len(result.slot_updates),
                clarification_required=result.clarification_required,
                recent_utterance_count=len(request.recent_utterances),
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise TaskIntakeError("计划草稿格式异常，请换一种说法重试") from error
        except ModelGatewayError as error:
            if str(error) == "invalid_model_candidate":
                raise TaskIntakeError("计划草稿格式异常，请换一种说法重试") from error
            raise TaskIntakeError("计划整理暂不可用，请稍后重试") from error
        except Exception as error:
            raise TaskIntakeError("计划整理暂不可用，请稍后重试") from error
        if result.clarification_required or not result.operations:
            result.ready_to_confirm = False
        return result
