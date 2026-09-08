from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from ..ai_agents.planning_domain_service import PlanningDomainService
from ..ai_agents.planning_workflow import build_planning_graph
from ..config import settings
from ..memory import SqlAlchemyMemoryFacade
from ..models import AgentRun
from .context_builder import ContextBuilder
from .contracts import RunInvocation, WorkflowOutcome


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
        )
        items = invocation.turn.get("planning_items")
        confirm = bool(invocation.turn.get("planning_confirm"))
        if self.checkpointer is not None:
            return self._invoke(
                self.checkpointer, run, items, confirm, envelope.trace_snapshot()
            )
        with _postgres_checkpointer() as checkpointer:
            return self._invoke(
                checkpointer, run, items, confirm, envelope.trace_snapshot()
            )

    def _invoke(
        self,
        checkpointer,
        run: AgentRun,
        items: list[dict] | None,
        confirm: bool,
        context_snapshot: dict,
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
            return WorkflowOutcome(
                run_status=run.status,
                next_interaction=result["__interrupt__"][0].value,
                checkpoint_ref=run.graph_checkpoint_ref,
                context_snapshot=context_snapshot,
            )
        outcome = result.get("outcome", {"status": "needs_input"})
        run.status = (
            "closed" if outcome.get("status") == "confirmed" else "waiting_for_ward"
        )
        return WorkflowOutcome(
            run_status=run.status,
            next_interaction=outcome,
            checkpoint_ref=run.graph_checkpoint_ref,
            context_snapshot=context_snapshot,
        )
