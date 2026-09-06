from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from ..ai_agents.planning_domain_service import PlanningDomainService
from ..ai_agents.planning_workflow import build_planning_graph
from ..config import settings
from ..models import AgentRun


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

    def invoke(self, *, run: AgentRun, items: list[dict] | None, confirm: bool) -> dict:
        if self.checkpointer is not None:
            return self._invoke(self.checkpointer, run, items, confirm)
        with _postgres_checkpointer() as checkpointer:
            return self._invoke(checkpointer, run, items, confirm)

    def _invoke(
        self, checkpointer, run: AgentRun, items: list[dict] | None, confirm: bool
    ) -> dict:
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
            return {
                "status": run.status,
                "interaction": result["__interrupt__"][0].value,
            }
        outcome = result.get("outcome", {"status": "needs_input"})
        run.status = (
            "closed" if outcome.get("status") == "confirmed" else "waiting_for_ward"
        )
        return {"status": run.status, "interaction": outcome}
