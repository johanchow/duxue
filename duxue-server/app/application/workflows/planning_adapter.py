from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.application.workflows.planning_workflow import build_planning_graph
from app.bootstrap.settings import settings
from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.infrastructure.persistence.models import AgentRun, Task, Ward
from app.application.commands.plan_intake import PlanIntakeInput, PlanIntakeService
from app.application.queries.context_builder import ContextBuilder
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.contexts.companion.domain.policy import PolicyRegistry
from app.infrastructure.ai.model_gateway import ModelGatewayError, QwenAgentModelGateway
from app.infrastructure.observability.telemetry import record_llm_fallback
from app.bootstrap.settings import settings


@contextmanager
def _postgres_checkpointer():
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with PostgresSaver.from_conn_string(url) as saver:
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
        confirm = bool(invocation.turn.get("planning_confirm"))
        assistant_text = None
        if not confirm and items is None:
            ward = self.db.get(Ward, run.ward_id)
            tasks = self.db.query(Task).filter_by(ward_id=run.ward_id).filter(Task.status != "completed").all()
            extracted = PlanIntakeService().respond(
                ward={"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage},
                tasks=[{"id": task.id, "title": task.title, "details": task.details} for task in tasks],
                request=PlanIntakeInput(content=invocation.turn["content"], draft_items=[], attachment_keys=invocation.turn.get("attachment_keys", [])),
            )
            items = [item.model_dump(mode="json") for item in extracted.items]
            assistant_text = extracted.assistant_text
        model_guidance, model_fallback = None, False
        if not confirm:
            try:
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
                self.checkpointer, run, items, confirm, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback
            )
        with _postgres_checkpointer() as checkpointer:
            return self._invoke(
                checkpointer, run, items, confirm, envelope.trace_snapshot(), model_guidance or assistant_text, model_fallback
            )

    def _invoke(
        self,
        checkpointer,
        run: AgentRun,
        items: list[dict] | None,
        confirm: bool,
        context_snapshot: dict,
        model_guidance: str | None,
        model_fallback: bool,
    ) -> WorkflowOutcome:
        graph = build_planning_graph(PlanningDomainService(self.db)).compile(
            checkpointer=checkpointer
        )
        config = {"configurable": {"thread_id": run.id}}
        if confirm and run.status == "waiting_for_ward":
            result = graph.invoke(Command(resume={"action": "confirm"}), config)
        else:
            proposed = items or []
            result = graph.invoke(
                {
                    "ward_id": run.ward_id,
                    "plan_date": datetime.now(timezone.utc).date().isoformat(),
                    "items": proposed,
                    "pending_fields": [] if proposed else ["tasks"],
                },
                config,
            )
        if "__interrupt__" in result:
            run.status, run.graph_checkpoint_ref = "waiting_for_ward", run.id
            interaction = dict(result["__interrupt__"][0].value)
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
