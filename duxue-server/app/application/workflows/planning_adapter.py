from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.application.commands.plan_intake import PlanIntakeInput, PlanIntakeService
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.queries.context_builder import ContextBuilder
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.application.workflows.planning_workflow import build_planning_graph
from app.bootstrap.settings import settings
from app.contexts.companion.domain.policy import PolicyRegistry
from app.contexts.planning.domain.scheduling import TaskReferenceResolver
from app.infrastructure.ai.model_gateway import ModelGatewayError, QwenAgentModelGateway
from app.infrastructure.observability.telemetry import (
    planning_stage_span,
    record_llm_fallback,
)
from app.infrastructure.persistence.models import AgentRun, PlanDraft, Task, Ward

_PLANNING_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def planning_today(current: datetime | None = None):
    """Return the Ward-facing calendar day; persisted timestamps remain UTC."""
    moment = current or datetime.now(timezone.utc)
    return moment.astimezone(_PLANNING_TIME_ZONE).date()


@contextmanager
def _postgres_checkpointer():
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with planning_stage_span("checkpointer_connect"), PostgresSaver.from_conn_string(url) as saver:
        with planning_stage_span("checkpointer_setup"):
            saver.setup()
        yield saver


class PlanningWorkflowAdapter:
    """Production always uses PostgreSQL persistence; tests inject a saver."""

    def __init__(self, db: Session, *, checkpointer=None):
        self.db = db
        self.checkpointer = checkpointer

    def invoke(self, *, invocation: RunInvocation) -> WorkflowOutcome:
        run = self.db.get(AgentRun, invocation.run_id)
        if run is None:
            raise ValueError("planning invocation references no run")
        with planning_stage_span("context_build", run_id=run.id):
            envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
                run_id=run.id,
                ward_id=run.ward_id,
                actor_id=run.ward_id,
                actor_role="ward",
                agent_type="planning",
                context_refs=invocation.context_refs,
                context_spec=PolicyRegistry().context_spec("planning"),
            )
        items = invocation.turn.get("planning_items")
        structured = invocation.turn.get("structured_command") or {}
        confirm = bool(invocation.turn.get("planning_confirm")) or structured.get("command") == "confirm_plan"
        assistant_text = None
        pending_fields: list[str] = []
        service = PlanningDomainService(self.db)
        prepared_draft_id = None
        if not confirm and structured.get("command") == "clarify_reply":
            payload = structured.get("payload") or {}
            draft = service.apply_operations(run.ward_id, planning_today(), [],
                answers=payload.get("answers") or [], command_id=invocation.command_id)
            items, pending_fields = draft.items, draft.pending_fields
            prepared_draft_id = draft.id
            assistant_text = "已记录补充的信息。"
        elif not confirm and items is None:
            ward = self.db.get(Ward, run.ward_id)
            tasks = self.db.query(Task).filter_by(ward_id=run.ward_id).filter(Task.status != "completed").all()
            active_draft = service.active_draft(run.ward_id, planning_today())
            slots = deepcopy(((active_draft.working_state or {}).get("active_clarification_batch") or {}).get("slots", [])) if active_draft else []
            # Only slot IDs are model-visible capabilities; Task IDs are resolved
            # by trusted code from candidate names, including multiselect replies.
            model_slots = [{"slot_id": slot["slot_id"], "field": slot["field"], "title": slot.get("title"),
                            "candidates": [c["title"] for c in slot.get("candidates", [])],
                            "choices": slot.get("choices", []), "question": slot.get("question")} for slot in slots]
            with planning_stage_span("plan_intake", run_id=run.id):
                extracted = PlanIntakeService().respond(
                    ward={"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage},
                    tasks=[{"title": task.title, "details": task.details, "planned_minutes": task.planned_minutes,
                            "scheduled": bool(task.schedule_id)} for task in tasks],
                    request=PlanIntakeInput(content=invocation.turn.get("content", ""),
                        draft_items=active_draft.items if active_draft else [], clarification_slots=model_slots,
                        attachment_keys=invocation.turn.get("attachment_keys", [])),
                )
            answers = deepcopy(extracted.slot_updates)
            accepted_answers = []
            for answer in answers:
                slot = next((s for s in slots if s["slot_id"] == answer.get("slot_id")), None)
                if slot and slot["field"] == "target_task_ids" and not answer.get("skip"):
                    if not slot.get("candidates"):
                        continue
                    names = answer.get("value")
                    names = names if isinstance(names, list) else [names]
                    values = []
                    for name in names:
                        matches = [c for c in slot.get("candidates", []) if c["title"] == name]
                        if len(matches) != 1:
                            raise HTTPException(400, "请从当前候选名称中明确选择任务")
                        values.append(matches[0]["id"])
                    answer["value"] = values
                if slot and slot["field"] == "title_conflict" and not answer.get("skip"):
                    value = answer.get("value")
                    if isinstance(value, dict) and value.get("action") == "use_existing" and not value.get("task_id"):
                        title = value.get("title") or value.get("task_title")
                        matches = [candidate for candidate in slot.get("candidates", [])
                                   if TaskReferenceResolver.normalise(candidate["title"])
                                   == TaskReferenceResolver.normalise(title)]
                        if len(matches) != 1:
                            raise HTTPException(400, "请从当前同名任务中明确选择")
                        value["task_id"] = matches[0]["id"]
                        answer["value"] = value
                accepted_answers.append(answer)
            answers = accepted_answers
            operations = [op.model_dump(exclude_none=True) for op in extracted.operations]
            if not operations:
                # Old model responses remain readable without trusting their IDs.
                candidates = [{"id": t.id, "title": t.title} for t in tasks]
                for item in extracted.items:
                    raw = item.model_dump(exclude_none=True)
                    ref = raw.get("task_reference") or raw.get("title")
                    existing = TaskReferenceResolver.resolve(ref, candidates)
                    operation = {k: v for k, v in raw.items() if k in {
                        "title", "planned_minutes", "start_at", "after_task_reference", "before_task_reference"}}
                    if existing or raw.get("task_reference"):
                        operation.update(kind="update", references=[ref])
                        operation.pop("title", None)
                    else:
                        operation["kind"] = "create"
                    operations.append(operation)
            draft = service.apply_operations(run.ward_id, planning_today(), operations,
                answers=answers, command_id=invocation.command_id)
            items, pending_fields = draft.items, draft.pending_fields
            prepared_draft_id = draft.id
            assistant_text = extracted.assistant_text
        elif not confirm:
            items, target_pending = service.resolve_task_references(
                run.ward_id, items or [], trust_explicit_ids=True)
            pending_fields = sorted(target_pending)
            if any(item.get("planned_minutes") is None for item in items):
                pending_fields.append("planned_minutes")
        model_guidance, model_fallback = None, False
        if not confirm and not pending_fields:
            try:
                with planning_stage_span("agent_text", run_id=run.id):
                    candidate = QwenAgentModelGateway().generate(
                        agent_type="planning", envelope=envelope.model_dump(),
                        instruction="根据已有任务，给一条简短的计划审阅提示；不得创建任务或声称已确认计划。",
                    )
                if PolicyRegistry().validate_candidate(candidate.model_dump(), allowed_tools=set()).accepted:
                    model_guidance = candidate.content
            except ModelGatewayError as error:
                model_fallback = True
                record_llm_fallback(operation="agent_text", reason=str(error))
        if self.checkpointer is not None:
            return self._invoke(
                self.checkpointer, run, items, confirm, pending_fields, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback, structured, prepared_draft_id
            )
        with _postgres_checkpointer() as checkpointer:
            return self._invoke(
                checkpointer, run, items, confirm, pending_fields, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback, structured, prepared_draft_id
            )

    @staticmethod
    def _operation_summary(view):
        labels = {"applied": "已保存", "waiting": "待补充", "rejected": "未修改", "deferred": "本次暂不安排"}
        return "；".join(
            labels.get(result['status'], result['status']) + "：" + "、".join(result.get('titles', []))
            + ("（" + result['reason'] + "）" if result.get('reason') else "")
            for result in view.get('operation_results', []))

    def _clarification_outcome(
        self, *, run: AgentRun, draft: PlanDraft, resolved_count: int, context_snapshot: dict,
    ) -> WorkflowOutcome:
        view = PlanningDomainService(self.db).plan_draft_view(run.ward_id, draft.id)
        batch = view.get("clarification_batch")
        # This helper is deliberately incapable of issuing confirm_plan.
        # Confirmation is signed only in _invoke after LangGraph yielded the
        # review interrupt that owns the resumable state.
        if batch:
            labels = {"title": "名字", "planned_minutes": "预计时长", "start_at": "开始时间", "target_task_ids": "具体任务（可明确选择多项）"}
            questions = [slot.get('question') or f"“{slot.get('title') or '这个任务'}”的{labels.get(slot['field'], slot['field'])}"
                         for slot in batch.get("slots", [])]
            text = "还需要补充：" + "、".join(questions) + "。也可以明确说明本次暂不安排。"
            kind = "clarify"
            actions = [{"name": "reply", "label": "补充信息", "command": "clarify_reply",
                        "id": f"clarify:{run.id}:{run.attempt}:{draft.id}:{draft.version}",
                        "enabled": True, "payload_schema": "clarification-batch.v1"}]
        elif resolved_count:
            text = "已记录任务预计时长。如果有开始时间，或想安排在什么任务之前、之后，可以告诉我。"
            kind = "clarify"
            actions = [{"name": "reply", "label": "补充信息", "command": "clarify_reply",
                        "id": f"clarify:{run.id}:{run.attempt}:{draft.id}:{draft.version}",
                        "enabled": True, "payload_schema": None}]
        else:
            text = "请补充任务预计时长。"
            kind = "clarify"
            actions = [{"name": "reply", "label": "补充信息", "command": "clarify_reply",
                        "id": f"clarify:{run.id}:{run.attempt}:{draft.id}:{draft.version}",
                        "enabled": True, "payload_schema": None}]
        summary = self._operation_summary(view)
        if summary:
            text = summary + "。" + text
        run.status = "waiting_for_ward"
        interaction = {
            "protocol": "companion-interaction.v1", "kind": kind,
            "run_id": run.id, "turn_id": run.current_turn_id, "attempt": run.attempt,
            "content": text, "parts": [{"type": "text", "text": text}],
            "object_ref": {"context": "planning", "object_type": "plan_draft",
                           "object_id": draft.id, "object_version": draft.version,
                           "query": "GetPlanDraft"},
            "actions": actions,
            "model": settings.agent_model("planning"), "model_fallback": False,
        }
        return WorkflowOutcome(run_status=run.status, next_interaction=interaction,
                               checkpoint_ref=run.graph_checkpoint_ref,
                               context_snapshot=context_snapshot)

    def _invoke(
        self,
        checkpointer,
        run: AgentRun,
        items: list[dict] | None,
        confirm: bool,
        pending_fields: list[str],
        context_snapshot: dict,
        model_guidance: str | None,
        model_fallback: bool,
        structured_command: dict,
        prepared_draft_id: str | None = None,
    ) -> WorkflowOutcome:
        with planning_stage_span("graph_compile", run_id=run.id):
            graph = build_planning_graph(PlanningDomainService(self.db)).compile(
                checkpointer=checkpointer
            )
        config = {"configurable": {"thread_id": run.id}}
        with planning_stage_span("graph_invoke", run_id=run.id, confirm=confirm):
            # Coordinator marks a resumed focus Run active before dispatch.
            # confirm_plan must nevertheless resume the checkpoint that issued
            # the action; falling through with empty items would overwrite the
            # reviewed draft and can never confirm it.
            if confirm:
                payload = structured_command.get("payload") or {}
                snapshot = graph.get_state(config)
                if not snapshot.next or "wait_for_confirmation" not in snapshot.next:
                    raise HTTPException(409, "审阅执行状态已失效，请重新打开草稿")
                if payload.get("draft_id") and snapshot.values.get("draft_id") != payload["draft_id"]:
                    raise HTTPException(409, "确认动作不属于当前草稿")
                result = graph.invoke(Command(resume={"action": "confirm", "expected_draft_version": payload.get("expected_draft_version")}), config)
            else:
                proposed = items or []
                result = graph.invoke(
                    {
                        "prepared_draft_id": prepared_draft_id,
                        "ward_id": run.ward_id,
                        "plan_date": planning_today().isoformat(),
                        "items": proposed,
                        "pending_fields": pending_fields or ([] if proposed else ["tasks"]),
                    },
                    config,
                )
        if "__interrupt__" in result:
            run.status, run.graph_checkpoint_ref = "waiting_for_ward", run.id
            review = dict(result["__interrupt__"][0].value)
            new_task_titles = [
                str(item.get("title", "")).strip() for item in (items or [])
                if item.get("new_task") and item.get("planned_minutes") is not None
            ]
            needs_schedule = not review["confirm_enabled"]
            if "ambiguous_target_task" in review.get("pending_fields", []):
                visible_text = "我还不能确定这个时间属于哪一项任务。请告诉我先开始哪一项。"
                kind = "clarify"
                actions = [{"name": "reply", "label": "继续说明", "command": "clarify_reply",
                            "enabled": True, "payload_schema": None}]
            elif new_task_titles and needs_schedule:
                titles = "、".join(f"“{title}”" for title in new_task_titles if title)
                visible_text = (
                    f"已添加{titles}任务。如果有计划的开始时间，或想安排在什么任务之前、之后，"
                    "可以告诉我，我会把它排进计划。"
                )
                kind = "clarify"
                actions = [{"name": "reply", "label": "继续说明", "command": "clarify_reply",
                            "enabled": True, "payload_schema": None}]
            elif needs_schedule:
                if review.get("conflicts"):
                    conflict_ids = {i for c in review["conflicts"] for i in c["task_ids"]}
                    titles = "、".join(i["title"] for i in review["items"] if i["assignment_id"] in conflict_ids)
                    visible_text = f"已保存修改，但{titles}的时间安排冲突或超过容量。请调整时间或明确本次不安排的任务。"
                elif "version_conflict" in review.get("pending_fields", []):
                    visible_text = "任务或日程已变化，请刷新并重新说明安排。"
                elif "unscheduled_reason" in review.get("pending_fields", []):
                    visible_text = "必做任务尚未安排，请补充安排或说明本次暂不安排的原因。"
                else:
                    visible_text = "任务已记录在任务池。如果要排入计划，可以告诉我开始时间或先后顺序。"
                kind = "clarify"
                actions = [{"name": "reply", "label": "继续说明", "command": "clarify_reply",
                            "enabled": True, "payload_schema": None}]
            else:
                if not run.graph_checkpoint_ref:
                    raise RuntimeError("cannot issue confirm_plan without a review checkpoint")
                visible_text = model_guidance or "请检查这份计划草稿。"
                kind = "plan_confirm_list"
                actions = [{"name": "confirm", "label": "确认这个计划", "command": "confirm_plan",
                            "id": f"plan:{run.id}:{run.attempt}:{review['draft_id']}:{review['object_version']}",
                            "enabled": review["confirm_enabled"],
                            "payload_schema": "confirm-plan.v1"}]
            summary = self._operation_summary(review)
            if summary:
                visible_text = summary + "。" + visible_text
            interaction = {
                "protocol": "companion-interaction.v1", "kind": kind,
                "run_id": run.id, "turn_id": run.current_turn_id, "attempt": run.attempt,
                "content": visible_text,
                "parts": [{"type": "text", "text": visible_text}],
                "object_ref": {"context": "planning", "object_type": "plan_draft",
                               "object_id": review["draft_id"], "object_version": review["object_version"],
                               "query": "GetPlanDraft"},
                "actions": actions,
            }
            interaction.update({"model": settings.agent_model("planning"), "model_fallback": model_fallback})
            if model_guidance:
                interaction["model_guidance"] = model_guidance
            return WorkflowOutcome(
                run_status=run.status,
                next_interaction=interaction,
                checkpoint_ref=run.graph_checkpoint_ref,
                context_snapshot=context_snapshot,
            )
        outcome = result.get("outcome", {"status": "needs_input"})
        if outcome.get("status") == "needs_input":
            draft = self.db.query(PlanDraft).filter_by(
                ward_id=run.ward_id, plan_date=planning_today(), status="active",
            ).one_or_none()
            if draft is not None:
                return self._clarification_outcome(
                    run=run, draft=draft, resolved_count=0, context_snapshot=context_snapshot,
                )
        run.status = (
            "closed" if outcome.get("status") == "confirmed" else "waiting_for_ward"
        )
        outcome["model"] = settings.agent_model("planning")
        outcome["model_fallback"] = model_fallback
        if model_guidance:
            outcome["model_guidance"] = model_guidance
        return WorkflowOutcome(
            run_status=run.status,
            next_interaction=outcome,
            checkpoint_ref=run.graph_checkpoint_ref,
            context_snapshot=context_snapshot,
        )
