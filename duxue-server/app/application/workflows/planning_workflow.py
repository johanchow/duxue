from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .planning_domain_service import PlanningDomainService


class PlanningState(TypedDict, total=False):
    ward_id: str
    plan_date: str
    items: list[dict]
    pending_fields: list[str]
    draft_id: str
    ready_for_confirmation: bool
    outcome: dict


def build_planning_graph(service: PlanningDomainService):
    """A bounded HITL graph with a write-free confirmation resume node."""

    def prepare_review(state: PlanningState) -> dict:
        draft = service.save_draft(
            state["ward_id"],
            date.fromisoformat(state["plan_date"]),
            state["items"],
            state.get("pending_fields", []),
        )
        if draft.pending_fields:
            return {
                "draft_id": draft.id,
                "ready_for_confirmation": False,
                "outcome": {
                    "status": "needs_input",
                    "pending_fields": draft.pending_fields,
                },
            }
        return {"draft_id": draft.id, "ready_for_confirmation": True}

    def route_after_prepare(state: PlanningState) -> Literal["review", "finish"]:
        return "review" if state.get("ready_for_confirmation") else "finish"

    def wait_for_confirmation(state: PlanningState) -> dict:
        # LangGraph re-enters an interrupted node.  The preceding node is the
        # only place that persists a draft, so resume cannot upgrade the
        # version or alter the snapshot Ward approved.
        view = service.plan_draft_view(state["ward_id"], state["draft_id"])
        command = interrupt({"type": "plan_review", **view})
        if not isinstance(command, dict) or command.get("action") != "confirm":
            return {"outcome": {"status": "waiting_for_ward"}}
        schedule = service.confirm(state["ward_id"], state["draft_id"], command.get("expected_draft_version"))
        return {
            "outcome": {"status": "confirmed", "schedule_id": schedule.id},
        }

    graph = StateGraph(PlanningState)
    graph.add_node("prepare_review", prepare_review)
    graph.add_node("wait_for_confirmation", wait_for_confirmation)
    graph.add_edge(START, "prepare_review")
    graph.add_conditional_edges(
        "prepare_review", route_after_prepare,
        {"review": "wait_for_confirmation", "finish": END},
    )
    graph.add_edge("wait_for_confirmation", END)
    return graph
