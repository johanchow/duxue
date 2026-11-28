"""Saved educational artifacts owned by the signed-in account."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian_or_ward, get_db
from app.api.deps import current_guardian
from app.application.commands import workspace_documents
from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from app.application.queries.artifact_library import saved_artifacts

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("")
def library(
    artifact_type: Literal[
        "creative_work", "interactive_courseware", "grading_report", "lesson_pack"
    ]
    | None = None,
    cursor: str | None = None,
    actor: Principal = Depends(current_guardian_or_ward),
    db: Session = Depends(get_db),
):
    return saved_artifacts(
        db,
        owner_id=actor.user_id,
        role=actor.role,
        artifact_type=artifact_type,
        cursor=cursor,
    )


class DocumentCommand(BaseModel):
    action: Literal["save", "revise", "undo", "redo"]
    command_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)
    instruction: str = Field(default="", max_length=2400)

    @model_validator(mode="after")
    def validate_instruction(self):
        if self.action == "revise" and not self.instruction.strip():
            raise ValueError("修订需要说明修改要求")
        return self


@router.get("/{artifact_id}")
def document(
    artifact_id: UUID,
    actor: Principal = Depends(current_guardian),
    db: Session = Depends(get_db),
):
    return workspace_documents.view(
        db, workspace_documents.owned(db, actor.user_id, artifact_id)
    )


@router.post("/{artifact_id}/commands")
def change(
    artifact_id: UUID,
    body: DocumentCommand,
    actor: Principal = Depends(current_guardian),
    db: Session = Depends(get_db),
):
    return workspace_documents.change(db, actor.user_id, artifact_id, body)
