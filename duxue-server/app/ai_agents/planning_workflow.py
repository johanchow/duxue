from __future__ import annotations

from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .planning_domain_service import PlanningDomainService


class PlanningState(TypedDict, total=False):
    ward_id: str
    plan_date: str
    items: list[dict]
    pending_fields: list[str]
    draft_id: str
    outcome: dict


def build_planning_graph(service: PlanningDomainService):
    """A bounded HITL graph; all writes remain in PlanningDomainService."""

    def review(state: PlanningState) -> dict:
        draft = service.save_draft(
            state["ward_id"],
            date.fromisoformat(state["plan_date"]),
            state["items"],
            state.get("pending_fields", []),
        )
        if draft.pending_fields:
            return {
                "draft_id": draft.id,
                "outcome": {
                    "status": "needs_input",
                    "pending_fields": draft.pending_fields,
                },
            }
        command = interrupt(
            {"type": "plan_review", "draft_id": draft.id, "items": draft.items}
        )
        if not isinstance(command, dict) or command.get("action") != "confirm":
            return {"draft_id": draft.id, "outcome": {"status": "waiting_for_ward"}}
        schedule = service.confirm(state["ward_id"], draft.id)
        return {
            "draft_id": draft.id,
            "outcome": {"status": "confirmed", "schedule_id": schedule.id},
        }

    graph = StateGraph(PlanningState)
    graph.add_node("review", review)
    graph.add_edge(START, "review")
    graph.add_edge("review", END)
    return graph
