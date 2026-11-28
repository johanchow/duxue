"""Account-owned persistent dialogue and navigation."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.infrastructure.persistence.courseware_tables import coursewares

from app.api.deps import Principal, current_guardian_or_ward, get_db
from app.application.commands.companion_history import lock_history, visible_threads
from app.infrastructure.persistence.models import (
    ConversationThread,
    GuardianConversationTurn,
    now,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


class ThreadTitle(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=80)


def owned(db, actor):
    if actor.role == "ward":
        return visible_threads(db, actor.user_id)
    return db.query(ConversationThread).filter_by(
        guardian_id=actor.user_id, deleted=False
    )


def thread_for(db, actor, thread_id, *, lock=False):
    if lock and actor.role == "ward":
        lock_history(db, actor.user_id)
    query = owned(db, actor).filter(ConversationThread.id == str(thread_id))
    row = (query.with_for_update() if lock else query).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "conversation unavailable")
    return row


def view(row):
    return {
        "thread_id": row.id,
        "title": row.title,
        "version": row.version,
        "history_generation": row.history_generation,
        "updated_at": row.updated_at,
    }


@router.get("")
def threads(
    limit: int = 50,
    cursor: str | None = None,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    page_size = max(1, min(limit, 100))
    query = owned(db, actor).order_by(
        ConversationThread.updated_at.desc(), ConversationThread.id.desc()
    )
    if cursor:
        anchor = owned(db, actor).filter(ConversationThread.id == cursor).one_or_none()
        if anchor is not None:
            query = query.filter(
                or_(
                    ConversationThread.updated_at < anchor.updated_at,
                    (ConversationThread.updated_at == anchor.updated_at)
                    & (ConversationThread.id < anchor.id),
                )
            )
    rows = query.limit(page_size + 1).all()
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = page[-1].id if has_more else None
    return {"items": [view(row) for row in page], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create(
    body: ThreadTitle,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    row = ConversationThread(title=body.title)
    if actor.role == "ward":
        row.history_generation = lock_history(db, actor.user_id).history_generation
        row.ward_id = actor.user_id
    else:
        row.guardian_id = actor.user_id
    db.add(row)
    db.commit()
    return view(row)


@router.patch("/{thread_id}")
def rename(
    thread_id: UUID,
    body: ThreadTitle,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    row = thread_for(db, actor, thread_id, lock=True)
    row.title = body.title
    db.commit()
    return view(row)


@router.delete("/{thread_id}", status_code=204)
def remove(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    if actor.role == "ward":
        lock_history(db, actor.user_id)
    row = (
        owned(db, actor)
        .filter(ConversationThread.id == str(thread_id))
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        return Response(status_code=204)
    row.deleted = True
    row.focus_run_ref = None
    row.version += 1
    db.commit()
    return Response(status_code=204)


@router.post("/{thread_id}/clear")
def clear(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    row = thread_for(db, actor, thread_id, lock=True)
    row.version += 1
    row.clear_version = row.version
    row.focus_run_ref = None
    if actor.role != "ward":
        row.history_generation += 1
    db.commit()
    return view(row)


@router.get("/{thread_id}/messages")
def messages(
    thread_id: UUID,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    row = thread_for(db, actor, thread_id)
    if actor.role == "ward":
        from app.api.v1.companion import _thread_messages_payload

        page = _thread_messages_payload(
            db, ward_id=actor.user_id, thread=row, before_thread_version=None, limit=100
        )
        return {**view(row), "items": page["messages"]}
    items = []
    turns = (
        db.query(GuardianConversationTurn)
        .filter_by(thread_id=row.id, generation=row.history_generation)
        .order_by(GuardianConversationTurn.position)
        .all()
    )
    keys = ["turn-" + turn.id for turn in turns]
    linked = (
        dict(
            db.execute(
                select(coursewares.c.command_id, coursewares.c.courseware_id).where(
                    coursewares.c.guardian_id == UUID(actor.user_id),
                    coursewares.c.command_id.in_(keys),
                    or_(
                        coursewares.c.retention_status == "saved",
                        coursewares.c.expires_at > now(),
                    ),
                )
            ).all()
        )
        if keys
        else {}
    )
    for turn in turns:
        items.extend(
            [
                {
                    "role": "user",
                    "message_id": turn.id,
                    "mode": turn.mode,
                    "content": turn.content,
                    "attachment_keys": turn.attachments,
                },
                {
                    **turn.reply,
                    "role": "assistant",
                    "mode": turn.mode,
                    "source_prompt": turn.content,
                    "source_keys": turn.attachments,
                    "courseware_id": linked.get("turn-" + turn.id),
                },
            ]
        )
    return {**view(row), "items": items}


@router.get("/{thread_id}/messages/{message_id}/images/{index}")
def source_image(
    thread_id: UUID,
    message_id: UUID,
    index: int,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    from app.application.workflows.guardian_experience import owns_image
    from app.infrastructure.storage.object_storage import storage

    row = thread_for(db, actor, thread_id)
    turn = (
        db.query(GuardianConversationTurn)
        .filter_by(
            id=str(message_id), thread_id=row.id, generation=row.history_generation
        )
        .one_or_none()
    )
    if turn is None or not 0 <= index < len(turn.attachments):
        raise HTTPException(404, "image unavailable")
    key = turn.attachments[index]
    if not owns_image(actor.user_id, key) or not storage.exists(key):
        raise HTTPException(404, "image unavailable")
    return Response(
        content=storage.read_limited(key, 12 * 1024 * 1024),
        media_type={"png": "image/png", "webp": "image/webp"}.get(
            key.rsplit(".", 1)[-1], "image/jpeg"
        ),
        headers={"Cache-Control": "private, no-store"},
    )
