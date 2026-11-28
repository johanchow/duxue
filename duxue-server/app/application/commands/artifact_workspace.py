"""Shared immutable document version chain and retention commands."""

from app.contexts.artifact_workspace.domain.versions import (
    MAX_VERSIONS,
    TEMPORARY_LIFETIME,
    active_prefix,
    move_cursor,
)
from fastapi import HTTPException
from sqlalchemy import func
from app.infrastructure.persistence.models import (
    ArtifactVersion,
    ArtifactCommand,
    EduArtifact,
    OutboxEvent,
    now,
)


def view(db, work):
    version = db.get(ArtifactVersion, (work.id, work.branch[work.cursor]))
    return {
        "artifact_id": work.id,
        "title": work.title,
        "saved": work.saved,
        "state_revision": work.revision,
        "version": version.number,
        "pages": version.pages,
        "can_undo": work.cursor > 0,
        "can_redo": work.cursor + 1 < len(work.branch),
    }


def apply(db, work, action, pages=None):
    if action == "save":
        if work.saved:
            return view(db, work)
        work.saved = True
    elif action in {"undo", "redo"}:
        try:
            work.cursor = move_cursor(work.branch, work.cursor, action)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    elif action == "revise" and pages:
        if work.cursor + 1 >= MAX_VERSIONS:
            raise HTTPException(409, "已达到单份资源的版本上限")
        latest = (
            db.query(func.max(ArtifactVersion.number))
            .filter_by(work_id=work.id)
            .scalar()
        )
        number = latest + 1
        db.add(ArtifactVersion(work_id=work.id, number=number, pages=pages))
        work.branch = [*active_prefix(work.branch, work.cursor), number]
        work.cursor += 1
    else:
        raise HTTPException(409, "version operation unavailable")
    work.revision += 1
    work.expires_at = None if work.saved else now() + TEMPORARY_LIFETIME
    if (
        work.artifact_type == "creative_work"
        and work.saved
        and action in ("save", "revise")
    ):
        db.add(
            OutboxEvent(
                aggregate_type="EduArtifact",
                aggregate_id=work.id,
                event_type="CreationFootprintRecorded.v1",
                payload={
                    "ward_id": work.ward_id,
                    "artifact_id": work.id,
                    "title": work.title,
                    "state_revision": work.revision,
                    "version": work.branch[work.cursor],
                },
            )
        )
    db.flush()
    return view(db, work)


def rename_saved(db, work, title: str):
    if not work.saved:
        raise HTTPException(409, "save work before renaming")
    cleaned = title.strip()
    if not cleaned or len(cleaned) > 80:
        raise HTTPException(422, "title must be 1 to 80 characters")
    work.title = cleaned
    work.revision += 1
    db.flush()
    return view(db, work)


def delete_saved(db, work):
    if not work.saved:
        raise HTTPException(409, "only saved work can be deleted")
    for table in (ArtifactCommand, ArtifactVersion):
        db.query(table).filter(table.work_id == work.id).delete(
            synchronize_session=False
        )
    db.delete(work)
    db.flush()


def expire_temporary(db):
    rows = (
        db.query(EduArtifact)
        .filter(EduArtifact.saved.is_(False), EduArtifact.expires_at <= now())
        .with_for_update(skip_locked=True)
        .limit(200)
        .all()
    )
    ids = [row.id for row in rows]
    if ids:
        for table in (ArtifactCommand, ArtifactVersion):
            db.query(table).filter(table.work_id.in_(ids)).delete(
                synchronize_session=False
            )
        db.query(EduArtifact).filter(EduArtifact.id.in_(ids)).delete(
            synchronize_session=False
        )
    db.commit()
    return len(ids)
