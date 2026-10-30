"""Visibility boundary for retained companion transcripts.

The Ward row is the serialization point for clears, turn acceptance and
outcome commits. Locks are released before dispatching a workflow.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import (
    AgentRun, CompanionCommand, ConversationThread, Ward, now,
)


def lock_history(db: Session, ward_id: str) -> Ward:
    ward = db.query(Ward).filter_by(id=ward_id).populate_existing().with_for_update().one_or_none()
    if ward is None:
        raise HTTPException(404, "ward not found")
    return ward


def visible_threads(db: Session, ward_id: str):
    return db.query(ConversationThread).join(Ward, Ward.id == ConversationThread.ward_id).filter(
        ConversationThread.ward_id == ward_id,
        ConversationThread.history_generation == Ward.history_generation,
    )


def history_is_visible(db: Session, ward_id: str, thread_id: str) -> bool:
    return visible_threads(db, ward_id).filter(ConversationThread.id == thread_id).first() is not None


def clear_history(db: Session, *, ward_id: str, command_id: str) -> dict:
    ward = lock_history(db, ward_id)
    digest = "companion.history.clear.v1"
    command = db.get(CompanionCommand, command_id)
    if command is not None:
        if command.ward_id != ward_id or command.payload_digest != digest:
            raise HTTPException(409, "command_id was already used with a different payload")
        return command.result
    previous_generation = ward.history_generation
    ward.history_generation += 1
    cleared_at = now()
    # Keep messages, attachments, checkpoints and audit records. Invalidating
    # focus and incrementing the version also fences already-running replies.
    old_threads = db.query(ConversationThread.id).filter_by(
        ward_id=ward_id, history_generation=previous_generation,
    )
    db.query(ConversationThread).filter_by(
        ward_id=ward_id, history_generation=previous_generation,
    ).update({
        ConversationThread.focus_run_ref: None,
        ConversationThread.version: ConversationThread.version + 1,
        ConversationThread.updated_at: cleared_at,
    }, synchronize_session=False)
    db.query(AgentRun).filter(
        AgentRun.ward_id == ward_id,
        AgentRun.thread_id.in_(old_threads),
        AgentRun.status.in_(("active", "waiting_for_ward", "paused", "failed", "timed_out")),
    ).update({AgentRun.status: "cancelled", AgentRun.cancelled_at: cleared_at}, synchronize_session=False)
    result = {"history_generation": ward.history_generation}
    db.add(CompanionCommand(id=command_id, ward_id=ward_id, payload_digest=digest,
                            result=result, completed_at=cleared_at))
    db.commit()
    db.expire_all()
    return result
