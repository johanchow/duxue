"""Ward-owned, non-persistent daily plan draft extraction."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from app.agent_specs.contexts import build_context
from app.agent_specs.release_runtime import configured_call
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import render_fragment
from app.infrastructure.ai.utterance_window import window_text
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
    duration_kind: Literal["completion_estimate", "timebox"] | None = None
    end_reminder_mode: Literal["scheduled", "elapsed", "off"] | None = None
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
    duration_kind: Literal["completion_estimate", "timebox"] | None = None
    end_reminder_mode: Literal["scheduled", "elapsed", "off"] | None = None
    start_at: str | None = None
    after_task_reference: str | None = None
    before_task_reference: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class PlanIntakeInput(BaseModel):
    """Internal Planning workflow input; it is deliberately independent of HTTP."""

    current_sprint: dict = Field(default_factory=dict)
    content: str = Field(default="", max_length=4000)
    draft_items: list[PlanIntakeItem] = Field(default_factory=list, max_length=30)
    clarification_slots: list[dict] = Field(default_factory=list, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)
    recent_utterances: list[dict] = Field(default_factory=list, max_length=8)
    omitted_utterance_count: int = Field(default=0, ge=0)
    self_review_aspects: list[dict] = Field(default_factory=list, max_length=4)


class StudyActionProposal(BaseModel):
    action: Literal["sprint_prepare", "sprint_pause", "sprint_resume", "sprint_end", "task_list", "task_time", "task_start", "task_pause", "task_resume", "task_end", "task_complete"]
    topic: str | None = Field(default=None, max_length=300)
    target_minutes: int | None = Field(default=None, ge=1, le=180)
    task_reference: str | None = Field(default=None, max_length=300)
    planned_start_at: datetime | None = None
    end_reminder_mode: Literal["elapsed", "off"] | None = None


class PlanIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False
    slot_updates: list[dict] = Field(default_factory=list, max_length=30)
    operations: list[PlanningOperation] = Field(default_factory=list, max_length=30)
    study_action: StudyActionProposal | None = None


def _prompt(ward: dict, tasks: list[dict], request: PlanIntakeInput) -> str:
    from app.agent_specs.definitions import load_definitions
    from app.infrastructure.ai.prompts import DynamicPrompt

    draft_items = []
    for item in request.draft_items:
        projected = item.model_dump()
        for identity_field in ("assignment_id", "after_assignment_id", "before_assignment_id"):
            projected.pop(identity_field, None)
        draft_items.append(projected)
    definition = load_definitions().units["planning.intake"].prompt
    prompt = DynamicPrompt(definition.id, definition.template, definition.variables)
    assert isinstance(prompt, DynamicPrompt)
    return prompt.render({
        "current_sprint": request.current_sprint,
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
        render_fragment("planning.intake", "history_omitted", count=str(request.omitted_utterance_count))
        if request.omitted_utterance_count else render_fragment("planning.intake", "history_complete")
    )
    return render_fragment("planning.intake", "history_block",
                           rules=render_fragment("planning.intake", "window_rules"),
                           utterances="\n".join(lines), omitted=omitted,
                           current_images=_current_image_block(current_ids))


def _current_image_block(current_ids: list[int]) -> str:
    if not current_ids:
        return ""
    return render_fragment("planning.intake", "current_images", ids="、".join(str(i) for i in current_ids))


class PlanIntakeService:
    @configured_call
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
