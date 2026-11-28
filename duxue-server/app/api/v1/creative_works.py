"""Student-owned storybooks, saved library and block-addressed revision commands."""

import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_ward, get_db
from app.application.commands import creative_works as works
from app.application.commands.companion_history import visible_threads
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded
from app.infrastructure.persistence.models import (
    CompanionMessage,
    ConversationThread,
    CreativeWork,
    CreativeWorkCommand,
)

router = APIRouter(prefix="/v1/creative-works", tags=["creative-works"])


class Mutation(BaseModel):
    action: Literal["save", "revise", "undo", "redo"]
    expected_revision: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=128)
    block_id: UUID | None = None
    instruction: str = Field(default="", max_length=1600)


def owned(db, actor, work_id, lock=False):
    query = (
        db.query(CreativeWork)
        .filter_by(id=str(work_id), ward_id=actor.user_id)
        .filter(
            or_(
                CreativeWork.saved.is_(True),
                CreativeWork.updated_at > works.temporary_cutoff(),
            )
        )
    )
    row = (query.with_for_update() if lock else query).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(404, "work unavailable")
    if not row.saved:
        thread = (
            visible_threads(db, actor.user_id)
            .filter(ConversationThread.id == row.source_thread_id)
            .first()
        )
        if thread is None or (
            thread.clear_version
            and not db.query(CompanionMessage.id)
            .filter(
                CompanionMessage.thread_id == thread.id,
                CompanionMessage.thread_version > thread.clear_version,
                CompanionMessage.interaction_ref["artifact_id"].as_string() == row.id,
            )
            .first()
        ):
            raise HTTPException(404, "work unavailable")
    return row


@router.get("")
def library(actor: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    rows = (
        db.query(CreativeWork)
        .filter_by(ward_id=actor.user_id, saved=True)
        .order_by(CreativeWork.updated_at.desc())
    )
    return {"items": [{"artifact_id": row.id, "title": row.title} for row in rows]}


@router.get("/{work_id}")
def details(
    work_id: UUID,
    actor: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    return works.view(db, owned(db, actor, work_id))


@router.post("/{work_id}/commands")
def change(
    work_id: UUID,
    body: Mutation,
    actor: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()

    def check(work):
        receipt = db.get(CreativeWorkCommand, (work.id, body.command_id))
        if receipt and receipt.digest == digest:
            return receipt.result
        if receipt or work.revision != body.expected_revision:
            raise HTTPException(409, "work changed; reload before editing")
        return None

    work = owned(db, actor, work_id, lock=True)
    cached = check(work)
    if cached is not None:
        return cached
    pages = None
    if body.action == "revise":
        snapshot = works.view(db, work)
        pages = list(snapshot["pages"])
        index = next(
            (
                i
                for i, page in enumerate(pages)
                if page["block_id"] == str(body.block_id)
            ),
            None,
        )
        if index is None or not body.instruction.strip():
            raise HTTPException(422, "select a page and describe your change")
        db.commit()
        try:
            candidate = works.generate(
                {
                    "instruction": body.instruction,
                    "selected_page": index + 1,
                    "title": snapshot["title"],
                    "pages": pages,
                }
            )
        except (ModelGatewayError, ModelTimeBudgetExceeded, ValidationError) as error:
            raise HTTPException(503, "绘本修改暂时未完成，请重试") from error
        if candidate is None:
            raise HTTPException(422, "这次修改需要你先说出自己的创作想法")
        if len(candidate.pages) != 1:
            raise HTTPException(503, "未生成单页修改，请重试")
        pages[index] = dict(
            candidate.pages[0].model_dump(), block_id=str(body.block_id)
        )
        work = owned(db, actor, work_id, lock=True)
        cached = check(work)
        if cached is not None:
            return cached
    result = works.apply(db, work, body.action, pages)
    db.add(
        CreativeWorkCommand(
            work_id=work.id, command_id=body.command_id, digest=digest, result=result
        )
    )
    db.commit()
    return result
