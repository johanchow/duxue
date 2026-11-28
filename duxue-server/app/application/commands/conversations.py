"""Application commands & queries for multi-conversation ConversationThread management."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.application.commands.companion_history import lock_history, visible_threads
from app.infrastructure.persistence.courseware_tables import coursewares
from app.infrastructure.persistence.models import (
    ConversationThread,
    GuardianConversationTurn,
    GuardianWard,
    now,
)


def owned_threads_query(db: Session, *, actor_id: str, actor_role: str):
    if actor_role == "ward":
        return visible_threads(db, actor_id)
    return db.query(ConversationThread).filter_by(guardian_id=actor_id, deleted=False)


def thread_for(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    thread_id: UUID | str,
    lock: bool = False,
) -> ConversationThread:
    if lock and actor_role == "ward":
        lock_history(db, actor_id)
    query = owned_threads_query(db, actor_id=actor_id, actor_role=actor_role).filter(
        ConversationThread.id == str(thread_id)
    )
    row = (query.with_for_update() if lock else query).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "conversation unavailable")
    return row


def thread_view(row: ConversationThread) -> dict:
    return {
        "thread_id": row.id,
        "title": row.title,
        "context_ward_id": row.context_ward_id,
        "version": row.version,
        "history_generation": row.history_generation,
        "updated_at": row.updated_at,
    }


def _validate_context_ward(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    context_ward_id: UUID | str | None,
) -> str | None:
    if context_ward_id is None:
        return None
    if actor_role == "ward":
        raise HTTPException(403, "ward cannot bind context_ward_id")
    binding = (
        db.query(GuardianWard)
        .filter_by(guardian_id=actor_id, ward_id=str(context_ward_id))
        .first()
    )
    if binding is None:
        raise HTTPException(403, "not bound to target ward")
    return str(context_ward_id)


def list_threads(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    limit: int = 50,
    cursor: str | None = None,
) -> dict:
    page_size = max(1, min(limit, 100))
    query = owned_threads_query(db, actor_id=actor_id, actor_role=actor_role).order_by(
        ConversationThread.updated_at.desc(), ConversationThread.id.desc()
    )
    if cursor:
        anchor = (
            owned_threads_query(db, actor_id=actor_id, actor_role=actor_role)
            .filter(ConversationThread.id == cursor)
            .one_or_none()
        )
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
    return {"items": [thread_view(row) for row in page], "next_cursor": next_cursor}


def create_thread(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    title: str = "新对话",
    context_ward_id: UUID | str | None = None,
) -> dict:
    bound_ward = _validate_context_ward(
        db, actor_id=actor_id, actor_role=actor_role, context_ward_id=context_ward_id
    )
    row = ConversationThread(title=title, context_ward_id=bound_ward)
    if actor_role == "ward":
        row.history_generation = lock_history(db, actor_id).history_generation
        row.ward_id = actor_id
    else:
        row.guardian_id = actor_id
    db.add(row)
    db.commit()
    return thread_view(row)


def update_thread(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    thread_id: UUID | str,
    title: str | None = None,
    context_ward_id: UUID | str | None = None,
    clear_context_ward: bool = False,
) -> dict:
    row = thread_for(
        db, actor_id=actor_id, actor_role=actor_role, thread_id=thread_id, lock=True
    )
    if title is not None:
        row.title = title
    if clear_context_ward:
        if actor_role == "ward":
            raise HTTPException(403, "ward cannot modify context_ward_id")
        row.context_ward_id = None
    elif context_ward_id is not None:
        row.context_ward_id = _validate_context_ward(
            db, actor_id=actor_id, actor_role=actor_role, context_ward_id=context_ward_id
        )
    db.commit()
    return thread_view(row)


def delete_thread(
    db: Session, *, actor_id: str, actor_role: str, thread_id: UUID | str
) -> None:
    if actor_role == "ward":
        lock_history(db, actor_id)
    row = (
        owned_threads_query(db, actor_id=actor_id, actor_role=actor_role)
        .filter(ConversationThread.id == str(thread_id))
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        return
    row.deleted = True
    row.focus_run_ref = None
    row.version += 1
    db.commit()


def clear_thread(
    db: Session, *, actor_id: str, actor_role: str, thread_id: UUID | str
) -> dict:
    row = thread_for(
        db, actor_id=actor_id, actor_role=actor_role, thread_id=thread_id, lock=True
    )
    row.version += 1
    row.clear_version = row.version
    row.focus_run_ref = None
    if actor_role != "ward":
        row.history_generation += 1
    db.commit()
    return thread_view(row)


def get_thread_messages(
    db: Session, *, actor_id: str, actor_role: str, thread_id: UUID | str
) -> dict:
    row = thread_for(db, actor_id=actor_id, actor_role=actor_role, thread_id=thread_id)
    if actor_role == "ward":
        from app.api.v1.companion import _thread_messages_payload

        page = _thread_messages_payload(
            db, ward_id=actor_id, thread=row, before_thread_version=None, limit=100
        )
        return {**thread_view(row), "items": page["messages"]}
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
                    coursewares.c.guardian_id == UUID(actor_id),
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
    return {**thread_view(row), "items": items}


def read_thread_source_image(
    db: Session,
    *,
    actor_id: str,
    actor_role: str,
    thread_id: UUID | str,
    message_id: UUID | str,
    index: int,
) -> tuple[bytes, str]:
    from app.application.workflows.guardian_experience import owns_image
    from app.infrastructure.storage.object_storage import storage

    row = thread_for(db, actor_id=actor_id, actor_role=actor_role, thread_id=thread_id)
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
    if not owns_image(actor_id, key) or not storage.exists(key):
        raise HTTPException(404, "image unavailable")
    media_type = {"png": "image/png", "webp": "image/webp"}.get(
        key.rsplit(".", 1)[-1], "image/jpeg"
    )
    return storage.read_limited(key, 12 * 1024 * 1024), media_type
