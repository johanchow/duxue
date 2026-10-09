"""发音教学卡的校验后投影。发音是 tutor-turn.v1 的 act=pronounce，只读，不写 Study 事实。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.infrastructure.persistence.models import PronunciationLesson, uid

SUPPORTED_RATES = (0.5, 0.75, 1.0)
_FORBIDDEN = re.compile(r"https?://|<speak|<phoneme|speech_rate|voice_profile|ssml", re.IGNORECASE)


class PronunciationNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: str | None = None
    kind: Literal["stress", "linking", "weak_form", "reduction", "intonation"]
    explanation: str = Field(min_length=1, max_length=240)


class LessonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str = Field(min_length=1, max_length=300)
    locale: Literal["en-US", "en-GB"]
    introduction: str = Field(min_length=1, max_length=240)
    reading_guide: str = Field(min_length=1, max_length=480)
    notes: list[PronunciationNote] = Field(default_factory=list, max_length=5)


def lesson_view(row: PronunciationLesson) -> dict:
    return {
        "lesson_ref": row.id,
        "source_text": row.source_text,
        "locale": row.locale,
        "introduction": row.introduction,
        "reading_guide": row.reading_guide,
        "notes": row.notes,
        "speech_ref": row.speech_ref,
        "supported_rates": row.supported_rates,
        "version": row.version,
    }


def normalized(text: str) -> str:
    return " ".join(text.split())


def forbidden_text(value: str) -> bool:
    return _FORBIDDEN.search(value) is not None


def _object_ref(row: PronunciationLesson) -> dict:
    return {
        "context": "study",
        "object_type": "pronunciation_lesson",
        "object_id": row.id,
        "object_version": row.version,
        "query": "GetPronunciationLesson",
    }


def build_interaction(*, invocation: RunInvocation, kind: str, text: str, actions: list[dict] | None = None, row: PronunciationLesson | None = None) -> dict:
    parts: list[dict] = [{"type": "text", "text": text}]
    object_ref = _object_ref(row) if row is not None else None
    if object_ref is not None:
        parts.append({"type": "object_ref", "object_ref": object_ref})
    return {
        "protocol": "companion-interaction.v1",
        "kind": kind,
        "run_id": invocation.run_id,
        "turn_id": invocation.turn_id,
        "attempt": invocation.attempt,
        "parts": parts,
        "actions": actions or [],
        "object_ref": object_ref,
        "content": text,
    }




def project_lesson(db: Session, invocation: RunInvocation, lesson: LessonBody) -> WorkflowOutcome:
    notes = [note.model_dump() for note in lesson.notes]
    digest = hashlib.sha256(json.dumps({
        "source_text": lesson.source_text,
        "locale": lesson.locale,
        "introduction": lesson.introduction,
        "reading_guide": lesson.reading_guide,
        "notes": notes,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    existing = db.query(PronunciationLesson).filter_by(
        run_id=invocation.run_id, turn_id=invocation.turn_id, attempt=invocation.attempt,
    ).one_or_none()
    if existing is not None:
        if existing.payload_digest != digest or existing.ward_id != invocation.ward_id:
            raise HTTPException(409, "pronunciation lesson conflict")
        row = existing
    else:
        row = PronunciationLesson(
            id=uid(), ward_id=invocation.ward_id, thread_id=invocation.thread_id,
            run_id=invocation.run_id, turn_id=invocation.turn_id, attempt=invocation.attempt,
            source_text=lesson.source_text, locale=lesson.locale,
            introduction=lesson.introduction, reading_guide=lesson.reading_guide,
            notes=notes, speech_ref="", supported_rates=list(SUPPORTED_RATES),
            payload_digest=digest, version=1,
        )
        row.speech_ref = row.id
        db.add(row)
        db.flush()
    interaction = build_interaction(
        invocation=invocation, kind="pronunciation_lesson", text=lesson.introduction, row=row,
    )
    return WorkflowOutcome(
        run_status="waiting_for_ward", outcome_type="response",
        context_refs=[f"pronunciation_lesson:{row.id}"],
        next_interaction={**interaction, "status": "success", "lesson": lesson_view(row)},
    )
