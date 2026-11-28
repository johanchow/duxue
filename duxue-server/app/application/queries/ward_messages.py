"""Visible Ward history shared by conversation and companion interfaces."""

from sqlalchemy.orm import Session
from app.infrastructure.persistence.models import (
    CompanionCommand,
    CompanionMessage,
    ConversationThread,
)


def readable_reply(row: CompanionMessage) -> bool:
    return (
        row.author_type == "companion"
        and bool(row.content.strip())
        and (row.interaction_ref or {}).get("kind") != "pronunciation_lesson"
    )


def _serialize_message(row: CompanionMessage) -> dict:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "run_id": row.run_id,
        "turn_id": row.turn_id,
        "attempt": row.attempt,
        "command_id": row.command_id,
        "thread_version": row.thread_version,
        "author_type": row.author_type,
        "content": row.content,
        "can_read_aloud": readable_reply(row),
        "attachment_refs": row.attachment_refs,
        "interaction_ref": row.interaction_ref,
        "created_at": row.created_at,
    }


def chat_messages(db: Session):
    # Older clients persisted support receipts as ordinary companion messages.
    reminder = (
        db.query(CompanionCommand.id)
        .filter(
            CompanionCommand.id == CompanionMessage.command_id,
            CompanionCommand.payload_digest == "support.invitation.v1",
        )
        .exists()
    )
    return db.query(CompanionMessage).filter(~reminder)


def thread_messages_payload(
    db: Session,
    *,
    ward_id: str,
    thread: ConversationThread,
    before_thread_version: int | None,
    limit: int,
) -> dict:
    query = (
        chat_messages(db)
        .filter_by(thread_id=thread.id, ward_id=ward_id)
        .filter(CompanionMessage.thread_version > thread.clear_version)
    )
    if before_thread_version is not None:
        query = query.filter(CompanionMessage.thread_version < before_thread_version)
    rows = query.order_by(CompanionMessage.thread_version.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [_serialize_message(row) for row in reversed(rows)]
    next_before = rows[-1].thread_version if has_more and rows else None
    return {
        "thread_id": thread.id,
        "thread_version": thread.version,
        "messages": messages,
        "next_before_thread_version": next_before,
        "previous_thread_id": None,
    }
