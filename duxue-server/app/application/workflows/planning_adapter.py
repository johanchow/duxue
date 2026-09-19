from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.application.workflows.planning_workflow import build_planning_graph
from app.bootstrap.settings import settings
from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.infrastructure.persistence.models import AgentRun, PlanDraft, Task, Ward
from app.application.commands.plan_intake import PlanIntakeInput, PlanIntakeService
from app.application.queries.context_builder import ContextBuilder
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.contexts.companion.domain.policy import PolicyRegistry
from app.infrastructure.ai.model_gateway import ModelGatewayError, QwenAgentModelGateway
from app.infrastructure.observability.telemetry import planning_stage_span, record_llm_fallback


_PLANNING_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def planning_today(current: datetime | None = None):
    """Return the Ward-facing calendar day; persisted timestamps remain UTC."""
    moment = current or datetime.now(timezone.utc)
    return moment.astimezone(_PLANNING_TIME_ZONE).date()


@contextmanager
def _postgres_checkpointer():
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with planning_stage_span("checkpointer_connect"):
        with PostgresSaver.from_conn_string(url) as saver:
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
        # A slot_id form is protocol data, not language; it may bypass LLM.
        # It still enters the review graph below so confirm_plan always has a
        # corresponding interrupt checkpoint.
        if not confirm and structured.get("command") == "clarify_reply":
            payload = structured.get("payload") or {}
            resolved = service.resolve_duration_clarification(
                ward_id=run.ward_id, plan_date=planning_today(),
                answers=payload.get("answers"),
            )
            if resolved is not None:
                draft, _ = resolved
                items, pending_fields = list(draft.items), list(draft.pending_fields)
                assistant_text = "已记录补充的信息。"
        if not confirm and items is None:
            ward = self.db.get(Ward, run.ward_id)
            tasks = self.db.query(Task).filter_by(ward_id=run.ward_id).filter(Task.status != "completed").all()
            active_draft = self.db.query(PlanDraft).filter_by(
                ward_id=run.ward_id,
                plan_date=planning_today(),
                status="active",
            ).one_or_none()
            with planning_stage_span("plan_intake", run_id=run.id):
                extracted = PlanIntakeService().respond(
                    ward={"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage},
                    tasks=[{"title": task.title, "details": task.details} for task in tasks],
                    request=PlanIntakeInput(
                        content=invocation.turn["content"],
                        draft_items=active_draft.items if active_draft else [],
                        clarification_slots=((active_draft.working_state or {}).get("active_clarification_batch") or {}).get("slots", []) if active_draft else [],
                        attachment_keys=invocation.turn.get("attachment_keys", []),
                    ),
                )
            if extracted.slot_updates:
                resolved = service.resolve_duration_clarification(
                    ward_id=run.ward_id, plan_date=planning_today(),
                    answers=extracted.slot_updates,
                )
                if resolved is not None:
                    active_draft, _ = resolved
            items = [item.model_dump(mode="json") for item in extracted.items] or (active_draft.items if active_draft else [])
            assistant_text = extracted.assistant_text
            if extracted.clarification_required:
                pending_fields.append("planned_minutes")
            # The intake model may correctly handle a time statement without
            # restating the unresolved duration candidates.  Keep that batch
            # pending and let its targets survive this scheduling-only turn.
            if active_draft and (active_draft.working_state or {}).get("active_clarification_batch"):
                pending_fields.append("planned_minutes")
        elif not confirm:
            items = items or []
            if any(item.get("planned_minutes") is None for item in items):
                pending_fields.append("planned_minutes")
                assistant_text = "还需要补充每项任务的预计时长。"
        if not confirm:
            # Bind references before register_tasks.  Extracted model output is
            # never trusted to select an ID; legacy planning_items may retain
            # an already-authorized explicit ID for compatibility.
            items, target_pending = PlanningDomainService(self.db).resolve_task_references(
                run.ward_id, items or [], trust_explicit_ids=invocation.turn.get("planning_items") is not None,
            )
            pending_fields.extend(sorted(target_pending))
            current_draft = self.db.query(PlanDraft).filter_by(
                ward_id=run.ward_id, plan_date=planning_today(), status="active",
            ).one_or_none()
            has_duration_batch = bool(
                current_draft and (current_draft.working_state or {}).get("active_clarification_batch")
            )
            # The LLM may emit a schedule item with duration=null and resolve
            # that exact duration in slot_updates in the same response.  The
            # post-resolution state, not the pre-resolution model flag, is
            # authoritative.
            if not has_duration_batch and not any(item.get("planned_minutes") is None for item in items):
                pending_fields = [field for field in pending_fields if field != "planned_minutes"]
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
                self.checkpointer, run, items, confirm, pending_fields, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback, structured
            )
        with _postgres_checkpointer() as checkpointer:
            return self._invoke(
                checkpointer, run, items, confirm, pending_fields, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback, structured
            )

    def _clarification_outcome(
        self, *, run: AgentRun, draft: PlanDraft, resolved_count: int, context_snapshot: dict,
    ) -> WorkflowOutcome:
        view = PlanningDomainService(self.db).plan_draft_view(run.ward_id, draft.id)
        batch = view.get("clarification_batch")
        # This helper is deliberately incapable of issuing confirm_plan.
        # Confirmation is signed only in _invoke after LangGraph yielded the
        # review interrupt that owns the resumable state.
        if batch:
            titles = "、".join(f"“{slot.get('title')}”" for slot in batch.get("slots", []))
            text = (
                f"还需要补充 {titles} 的预计时长。请按任务名称分别说明，"
                "例如“数学试卷 30 分钟，英语作业 50 分钟”；也可以说“都 30 分钟”。"
            )
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
                result = graph.invoke(Command(resume={"action": "confirm", "expected_draft_version": payload.get("expected_draft_version")}), config)
            else:
                proposed = items or []
                result = graph.invoke(
                    {
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
                visible_text = "草稿已记录。请告诉我每项任务的开始时间，或想安排在什么任务之前、之后。"
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
