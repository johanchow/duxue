"""Unified Education General Agent endpoints (/v1/agent/*)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian_or_ward, expose_turn_trace, get_db
from app.api.schemas import WardAgentTurnRequest
from app.api.v1.companion import companion_turn
from app.api.v1.guardian_experience import ExperienceTurnRequest, execute_turn
from app.application.agent.role_policy import evaluate_role_policy, normalize_role
from app.application.commands.conversations import get_turn_result
from app.application.tools.core_tools import build_default_registries

router = APIRouter(prefix="/v1/agent", tags=["edu-agent"])


@router.get("/catalog")
def catalog(actor: Principal = Depends(current_guardian_or_ward)):
    role = normalize_role(actor.role)
    policy = evaluate_role_policy(role=role, context_ward_bound=False)
    _, skills = build_default_registries()
    return {
        "role": policy.role,
        "skills": skills.visible_catalog(policy),
        "base_tools": sorted(policy.base_tools),
    }


@router.post("/turns", dependencies=[Depends(expose_turn_trace)])
def run_turn(
    body: dict,
    request: Request,
    response: Response,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    """Dispatch by authenticated identity and preserve each domain's wire result and SSE."""
    payload = dict(body)
    if "message" in payload and "content" not in payload:
        payload["content"] = payload.pop("message")
    hint = payload.pop("skill_hint", None)
    if hint is not None:
        policy = evaluate_role_policy(
            role=normalize_role(actor.role), context_ward_bound=False
        )
        _, skills = build_default_registries()
        visible = {entry["id"] for entry in skills.visible_catalog(policy)}
        if not isinstance(hint, str) or hint not in visible:
            raise HTTPException(403, "skill not permitted")
        if hint in {"edu.lesson_pack", "edu.worksheet_grading"} and not payload.get(
            "thread_id"
        ):
            raise HTTPException(422, "生成资源需要来源对话")
        if hint not in {
            "edu.homework_tutoring",
            "edu.lesson_pack",
            "edu.worksheet_grading",
        } and not (actor.role != "ward" and hint == "edu.interactive_courseware"):
            raise HTTPException(501, "explicit skill invocation unavailable")
    ward = actor.role == "ward"
    try:
        turn = (WardAgentTurnRequest if ward else ExperienceTurnRequest).model_validate(
            payload
        )
    except ValidationError as error:
        raise RequestValidationError(error.errors(include_context=False)) from error
    if ward:
        return companion_turn(turn, request, response, actor, db)
    return execute_turn(turn, request, response, actor, db, plan=True, skill_hint=hint)


@router.get("/threads/{thread_id}/results/{command_id}")
def final_result(
    thread_id: UUID,
    command_id: str,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    """Recover a committed result for the currently visible conversation generation."""
    return get_turn_result(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        thread_id=thread_id,
        command_id=command_id,
    )
