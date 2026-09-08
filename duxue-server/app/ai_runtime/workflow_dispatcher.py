"""Dispatch a Coordinator invocation to exactly one registered workflow."""

from __future__ import annotations

from typing import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import AgentRun
from ..ai_agents.tutoring_workflow import TutoringWorkflow
from ..ai_agents.reflection_workflow import ReflectionWorkflow
from .contracts import RunInvocation, WorkflowOutcome


class SqlAlchemyWorkflowDispatcher:
    """Transitional composition adapter for the modular monolith."""

    def __init__(self, db: Session, *, planning_factory: Callable[[Session], object]):
        self.db = db
        self.planning_factory = planning_factory

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        run = self.db.get(AgentRun, invocation.run_id)
        if run is None or run.thread_id != invocation.thread_id or run.ward_id != invocation.ward_id:
            raise HTTPException(404, "agent run not found")
        if invocation.agent_type == "planning":
            return self.planning_factory(self.db).invoke(invocation=invocation)
        if invocation.agent_type == "tutoring":
            return TutoringWorkflow(self.db).invoke(invocation)
        if invocation.agent_type == "reflection":
            return ReflectionWorkflow(self.db).invoke(invocation)
        # Target workflows are intentionally metadata-only until implemented.
        return WorkflowOutcome(run_status="active")
