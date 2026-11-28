"""Unified Education General Agent endpoints (/v1/agent/*)."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian_or_ward, get_db
from app.application.agent.orchestrator import (
    EduAgentOrchestrator,
    OrchestratorStep,
    default_run_store,
)
from app.application.agent.registry import ToolContext
from app.application.agent.role_policy import evaluate_role_policy, normalize_role
from app.application.commands import conversations as conv_cmd
from app.application.tools.core_tools import build_default_registries

router = APIRouter(prefix="/v1/agent", tags=["edu-agent"])

_TOOL_REGISTRY, _SKILL_REGISTRY = build_default_registries()


class AgentTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: UUID | None = None
    context_ward_id: UUID | None = None
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)
    skill_hint: str | None = None


@router.get("/catalog")
def catalog(actor: Principal = Depends(current_guardian_or_ward)):
    role = normalize_role(actor.role)
    policy = evaluate_role_policy(role=role, context_ward_bound=False)
    return {
        "role": policy.role,
        "skills": _SKILL_REGISTRY.visible_catalog(policy),
        "base_tools": sorted(policy.base_tools),
    }


@router.post("/turns")
def run_turn(
    body: AgentTurnRequest,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    role = normalize_role(actor.role)
    resolved_thread_id: str | None = None
    bound_ward_id: str | None = None
    if body.thread_id is not None:
        thread = conv_cmd.thread_for(
            db, actor_id=actor.user_id, actor_role=actor.role, thread_id=body.thread_id
        )
        resolved_thread_id = thread.id
        bound_ward_id = thread.context_ward_id
    if body.context_ward_id is not None:
        bound_ward_id = conv_cmd._validate_context_ward(
            db,
            actor_id=actor.user_id,
            actor_role=actor.role,
            context_ward_id=body.context_ward_id,
        )

    orchestrator = EduAgentOrchestrator(
        tool_registry=_TOOL_REGISTRY,
        skill_registry=_SKILL_REGISTRY,
        run_store=default_run_store,
    )
    ctx = ToolContext(
        actor_id=actor.user_id,
        actor_role=role,
        thread_id=resolved_thread_id,
        context_ward_id=bound_ward_id,
        db=db,
    )

    def default_planner(state: dict) -> OrchestratorStep:
        if body.skill_hint and state["step_index"] == 0:
            return OrchestratorStep(action="load_skill", skill_id=body.skill_hint)
        return OrchestratorStep(
            action="respond",
            content=f"已收到你的请求：{body.message}",
            interaction_kind="text",
        )

    outcome = orchestrator.run(
        ctx=ctx,
        message=body.message,
        attachments=body.attachment_keys,
        planner=default_planner,
    )
    return {
        "run_id": outcome.run_id,
        "thread_id": resolved_thread_id,
        "status": outcome.status,
        "active_skill_id": outcome.active_skill_id,
        "registered_gates": sorted(outcome.registered_gates),
        "interaction": {
            "kind": outcome.interaction_kind,
            "content": outcome.content,
            "artifact_id": outcome.artifact_id,
        },
    }


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: str,
    actor: Principal = Depends(current_guardian_or_ward),
):
    rec = default_run_store.get(run_id)
    if rec is None or rec.owner_id != actor.user_id:
        raise HTTPException(404, "agent run not found")

    def stream():
        for idx, item in enumerate(rec.events):
            yield f"id: {idx}\nevent: {item.get('event', 'message')}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    actor: Principal = Depends(current_guardian_or_ward),
):
    rec = default_run_store.cancel(run_id, owner_id=actor.user_id)
    if rec is None:
        raise HTTPException(404, "agent run not found")
    return {"run_id": rec.run_id, "status": rec.status}
