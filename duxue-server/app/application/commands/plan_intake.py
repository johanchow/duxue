"""Ward-owned, non-persistent daily plan draft extraction."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from app.bootstrap.settings import settings
from app.infrastructure.ai.utterance_window import WINDOW_RULE
from app.infrastructure.observability.telemetry import (
    model_call_span,
    record_model_response,
    record_plan_intake_structure,
)

from .task_intake import TaskIntakeError, _data_url


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


class PlanIntakeResult(BaseModel):
    assistant_text: str = Field(min_length=1, max_length=4000)
    clarification_required: bool = False
    questions: list[str] = Field(default_factory=list, max_length=5)
    ready_to_confirm: bool = False
    slot_updates: list[dict] = Field(default_factory=list, max_length=30)
    operations: list[PlanningOperation] = Field(default_factory=list, max_length=30)


def _prompt(ward: dict, tasks: list[dict], request: PlanIntakeInput) -> str:
    draft_items = []
    for item in request.draft_items:
        projected = item.model_dump()
        for identity_field in ("assignment_id", "after_assignment_id", "before_assignment_id"):
            projected.pop(identity_field, None)
        draft_items.append(projected)
    return _recent_utterance_block(request) + f"""你是读学的当天计划整理助手。今天是 {datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()}。
你只能为当前学生生成今天的草稿，绝不能安排其他人或其他日期。
当前学生：{json.dumps(ward, ensure_ascii=False)}
当前未完成任务池：{json.dumps(tasks, ensure_ascii=False)}
当前尚未确认的草稿：{json.dumps(draft_items, ensure_ascii=False)}
当前待补槽位：{json.dumps(request.clarification_slots, ensure_ascii=False)}

硬规则：
1. 根据本轮学生输入或图片，保留、增加、删除或调整今天的草稿任务；不要编造作业内容、页码或截止日。
2. 绝不输出 assignment_id、after_assignment_id、before_assignment_id，也不要决定 new_task。引用任务池已有任务时，必须从当前任务池复制该任务的完整标题到 task_reference 与 title；即使本轮只是修改开始时间，也绝不能把已有任务改写成新任务。只有任务池中没有对应任务时才填写新 title 且 task_reference=null。服务端会负责绑定真实 Task ID。
3. 你负责理解自然语言：区分钟表时间（如“十九点三十分”）与持续时长（如“预计三十分钟”）。可同时输出 slot_updates 和 operations 里的排程字段。slot_updates 只能使用当前待补槽位中的 slot_id，形如 {{slot_id, value:"30分钟"}}；钟表时间绝不能填入 planned_minutes。新任务缺名字时 title=null 并追问，不编造名字。planned_minutes 只有学生明确说出、或图片上写明预计时长时才能填写（1 到 480）；绝不猜测或默认任何时长。学生明确给出开始时间时才填写 ISO 8601 start_at；绝不猜测开始时间。表达“在数学之后/英语之前”时填写 after_task_reference/before_task_reference（任务名称）。
4. 一个开始时间必须属于一个明确任务。任务池有多个候选而学生只说“18点开始”时，不得给多个 item 填同一个 start_at；保持时间为空并追问先做哪一项。
5. 只有草稿至少有一项、每项都有明确预计时长和可确定时间槽且信息足够明确时 ready_to_confirm=true。
6. 优先输出 operations，每项 kind=create/update/schedule/defer/delete；references 是本轮明确目标的名称数组，title 是新增或修改后的名字，planned_minutes 是明示的新耗时，start_at / after_task_reference / before_task_reference 是安排字段，reason 是明确暂不安排原因。delete 仅在学生明确要求删除/移除任务池任务时使用，必须填写 references，不得把“本次不安排”输出为 delete。同轮可以有多个操作；明确修改多个任务时放在同一个 references 数组，不把歧义的一个名称广播给多项。update/delete 不匹配时必须澄清或拒绝，绝不能自动变为 create。仅登记任务不追问开始时间；schedule 缺起点时需要澄清。未说出的字段省略。标题与任务池同名时不要自行判断，由服务端标题冲突槽位要求 Ward 选择。学生要求「同样的操作」或重复刚才的修改时，必须能从可见原句确定要重复的名字、时长或开始时间；确定不了就 operations 为 []、clarification_required=true，并在 questions 里询问要重复哪一项。不能把任务的当前标题原样写回 update。可见原句里已经写明那一次修改时，把同样的标题、时长和开始时间写到本轮点名的任务上，clarification_required=false。
7. slot_updates 回答缺名字、耗时、开始时间、目标选择或标题冲突。目标选择的 value 是所选候选的完整名称数组，不是 ID；标题冲突槽位的 value 使用 {{action:"use_existing", title:"已有任务完整标题"}}、{{action:"create_new"}}、{{action:"accept_duplicate"}} 或 {{action:"cancel"}}，不得编造 ID。只有当前槽位的 slot_id 可以回传。明确暂不安排某待补问题时输出 {{slot_id, skip:true, reason:"用户原因"}}。回答问题与独立操作可以同轮并存，但不重复输出同一修改。恢复待执行修改由服务端完成。
8. 只输出 JSON object：assistant_text、operations、slot_updates、clarification_required、questions、ready_to_confirm。""" + """
9. 图片里能读到的标题和时长是观察到的内容，不是编造。学生要求把图片收成任务、且内容明确是学习任务时，每条当前任务池里没有的标题必须输出一条 kind=create 的 operation，title 用图片中的标题；图片写明的时长写入 planned_minutes，没写就省略该字段。已经确定要创建时，不要只把清单写进 assistant_text。图片内容可能不是学习任务（例如行程、通知）时，不要创建：operations 为 []，clarification_required=true，在 assistant_text 和 questions 里说明看到了什么，并请学生确认要不要创建。图片读不清时同样 operations 为 []，assistant_text 说明读不清，clarification_required=true。
示例：{"assistant_text":"已从图片整理出任务，还需要预计时长。","operations":[{"kind":"create","title":"数学口算"}],"slot_updates":[],"clarification_required":false,"questions":[],"ready_to_confirm":false}"""


def _recent_utterance_block(request: PlanIntakeInput) -> str:
    if not request.recent_utterances:
        return ""
    lines = []
    for item in request.recent_utterances:
        speaker = "学生" if item.get("author") == "ward" else "读学"
        image = "（本句附有图片）" if item.get("had_image") else ""
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
        + "学生确认这些原句里列出的事项要创建时，为其中尚未出现在当前任务池的标题各输出一条 kind=create，并把学生明确说出的时长写入 planned_minutes。不要把「都」改写成任务池里已有的其他任务。本轮没有新图片时，以这些原句里已经写出的观察为准。\n\n"
    )


class PlanIntakeService:
    def respond(self, *, ward: dict, tasks: list[dict], request: PlanIntakeInput) -> PlanIntakeResult:
        if not request.content and not request.attachment_keys:
            raise TaskIntakeError("请先输入文字、说话或添加图片")
        try:
            from app.infrastructure.ai.client import dashscope_client

            client = dashscope_client()
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
                raw = response.choices[0].message.content or "{}"
            record_model_response(
                agent_type="planning", model=settings.task_intake_model, content=raw, operation="plan_intake",
            )
            result = PlanIntakeResult.model_validate_json(raw)
            record_plan_intake_structure(
                has_image=bool(request.attachment_keys),
                operation_count=len(result.operations),
                slot_update_count=len(result.slot_updates),
                clarification_required=result.clarification_required,
                recent_utterance_count=len(request.recent_utterances),
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise TaskIntakeError("计划草稿格式异常，请换一种说法重试") from error
        except Exception as error:
            raise TaskIntakeError("计划整理暂不可用，请稍后重试") from error
        if result.clarification_required or not result.operations:
            result.ready_to_confirm = False
        return result
