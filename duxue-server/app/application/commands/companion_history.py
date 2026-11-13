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


def append_support_invitation(db: Session, *, ward_id: str, offer_id: str, content: str):
    """Append once through the same Ward/thread version boundary as normal turns.

    Callers hold lock_history before taking the observation policy lock. The
    separately versioned support.v1 channel owns actions; historical text does
    not create live buttons in the existing conversational protocol.
    """
    from app.infrastructure.persistence.models import CompanionMessage
    ward = db.get(Ward, ward_id)
    existing = db.get(CompanionCommand, offer_id)
    if existing:
        if existing.ward_id != ward_id or existing.payload_digest != 'support.invitation.v1':
            raise HTTPException(409, 'invitation command identity conflict')
        return
    thread = visible_threads(db, ward_id).order_by(ConversationThread.updated_at.desc()).first()
    if thread is None:
        thread = ConversationThread(ward_id=ward_id, history_generation=ward.history_generation, version=0)
        db.add(thread)
        db.flush()
    thread.version += 1
    db.add(CompanionCommand(id=offer_id, ward_id=ward_id, thread_id=thread.id,
                           payload_digest='support.invitation.v1', result={'offer_id': offer_id}, completed_at=now()))
    db.flush()
    db.add(CompanionMessage(ward_id=ward_id, thread_id=thread.id, command_id=offer_id,
                           thread_version=thread.version, author_type='companion', content=content))
