"""Dispatch a Coordinator invocation to exactly one registered workflow."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from app.agent_specs.catalog import load_catalog
from app.agent_specs.definitions import load_definitions
from app.agent_specs.results import completed
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.bootstrap.math_engine import tutoring_workflow
from app.infrastructure.persistence.models import AgentRun


class SqlAlchemyWorkflowDispatcher:
    """Transitional composition adapter for the modular monolith."""

    def __init__(self, db: Session):
        self.db = db

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        run = self.db.get(AgentRun, invocation.run_id)
        if run is None or run.thread_id != invocation.thread_id or run.ward_id != invocation.ward_id:
            raise HTTPException(404, "agent run not found")
        factories = {
            "tutoring": tutoring_workflow,
        }
        workflow = load_catalog().spec(invocation.agent_type)
        agent = load_definitions().code_agents[workflow.invocation_agent]
        Draft202012Validator(agent.input_schema).validate(invocation.model_dump(mode="json"))
        invocation = RunInvocation.model_validate(invocation)
        handler = agent.handler_id
        if handler not in factories:
            raise ValueError(f"unregistered workflow handler: {handler}")
        result = factories[handler](self.db).invoke(invocation=invocation)
        typed = WorkflowOutcome.model_validate(result)
        public_result = typed.model_dump(mode="json")
        Draft202012Validator(agent.output_schema).validate(public_result)
        completed(public_result, needs_input=typed.run_status == "waiting_for_ward")
        # The coordinator also needs the private keys of reviewed attachments.
        return typed
