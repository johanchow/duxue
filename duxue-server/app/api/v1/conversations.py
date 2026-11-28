"""Thin FastAPI interface for account-owned multi-conversation threads."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian_or_ward, get_db
from app.application.commands import conversations as cmd

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


def thread_for(db: Session, actor: Principal, thread_id: UUID | str, *, lock: bool = False):
    return cmd.thread_for(
        db, actor_id=actor.user_id, actor_role=actor.role, thread_id=thread_id, lock=lock
    )


class CreateThreadRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=80)
    context_ward_id: UUID | None = None


class UpdateThreadRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    context_ward_id: UUID | None = None
    clear_context_ward: bool = False


@router.get("")
def threads(
    limit: int = 50,
    cursor: str | None = None,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return cmd.list_threads(
        db, actor_id=actor.user_id, actor_role=actor.role, limit=limit, cursor=cursor
    )


@router.post("", status_code=201)
def create(
    body: CreateThreadRequest,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return cmd.create_thread(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        title=body.title,
        context_ward_id=body.context_ward_id,
    )


@router.patch("/{thread_id}")
def update(
    thread_id: UUID,
    body: UpdateThreadRequest,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return cmd.update_thread(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        thread_id=thread_id,
        title=body.title,
        context_ward_id=body.context_ward_id,
        clear_context_ward=body.clear_context_ward,
    )


@router.delete("/{thread_id}", status_code=204)
def remove(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    cmd.delete_thread(db, actor_id=actor.user_id, actor_role=actor.role, thread_id=thread_id)
    return Response(status_code=204)


@router.post("/{thread_id}/clear")
def clear(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return cmd.clear_thread(
        db, actor_id=actor.user_id, actor_role=actor.role, thread_id=thread_id
    )


@router.get("/{thread_id}/messages")
def messages(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return cmd.get_thread_messages(
        db, actor_id=actor.user_id, actor_role=actor.role, thread_id=thread_id
    )


@router.get("/{thread_id}/messages/{message_id}/images/{index}")
def source_image(
    thread_id: UUID,
    message_id: UUID,
    index: int,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    content, media_type = cmd.read_thread_source_image(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        thread_id=thread_id,
        message_id=message_id,
        index=index,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{thread_id}/ward-summary")
def ward_summary(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    from app.application.agent.registry import ToolContext
    from app.application.agent.role_policy import normalize_role
    from app.application.tools.core_tools import handle_ward_context_read_summary
    row = thread_for(db, actor, thread_id)
    ctx = ToolContext(actor_id=actor.user_id, actor_role=normalize_role(actor.role),
                      thread_id=row.id, context_ward_id=row.context_ward_id, db=db)
    try:
        return handle_ward_context_read_summary({}, ctx)
    except PermissionError as error:
        raise HTTPException(403, "authorized student context required") from error
