"""Account-scoped library projection over the shared EduArtifact store."""

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_

from app.infrastructure.persistence.models import EduArtifact


def saved_artifacts(
    db,
    *,
    owner_id,
    role,
    artifact_type,
    cursor,
):
    before = None
    if cursor:
        try:
            stamp, identifier = cursor.split("|")
            before = datetime.fromisoformat(stamp), UUID(identifier)
        except ValueError as error:
            raise HTTPException(422, "invalid artifact cursor") from error
    kinds = (
        ["creative_work"]
        if role == "ward"
        else ["interactive_courseware", "grading_report", "lesson_pack"]
    )
    query = db.query(EduArtifact).filter(
        EduArtifact.owner_id == owner_id,
        EduArtifact.saved,
        EduArtifact.artifact_type.in_(kinds),
    )
    if artifact_type:
        query = query.filter(EduArtifact.artifact_type == artifact_type)
    if before:
        stamp, identifier = before
        query = query.filter(
            or_(
                EduArtifact.updated_at < stamp,
                (EduArtifact.updated_at == stamp) & (EduArtifact.id < str(identifier)),
            )
        )
    rows = (
        query.order_by(EduArtifact.updated_at.desc(), EduArtifact.id.desc())
        .limit(31)
        .all()
    )
    page = rows[:30]
    return {
        "items": [
            {
                "artifact_type": row.artifact_type,
                **(
                    {
                        "courseware_id": row.id,
                        "question_text": row.payload.get("question_text")
                        or row.payload.get("prompt_text"),
                        "thumbnail": row.payload.get("thumbnail"),
                        "subject": row.payload.get("subject"),
                    }
                    if row.artifact_type == "interactive_courseware"
                    else {}
                ),
                "artifact_id": row.id,
                "title": row.title,
                "updated_at": row.updated_at,
                "state_revision": row.revision,
            }
            for row in page
        ],
        "next_cursor": f"{page[-1].updated_at.isoformat()}|{page[-1].id}"
        if len(rows) > 30
        else None,
    }
