"""Authenticated adult experience, isolated from every Ward aggregate."""
import secrets
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api.v1.conversations import thread_for
from app.infrastructure.persistence.models import GuardianConversationTurn
from app.api.deps import Principal, current_guardian, expose_turn_trace, get_db
from app.api.reply_events import GUIDE_STAGES, stream_reply
from app.api.schemas import UploadUrlRequest
from app.application.queries.problem_dossier import GetProblemDossierQuery
from app.application.queries.pronunciation_speech import canonical_rate
from app.application.workflows.guardian_experience import (
    ExperienceMode,
    experience_turn,
    media_prefix,
    owns_image,
)
from app.application.workflows.guardian_mentor import (
    MENTOR_PURPOSE,
    MentorRateLimitExceeded,
)
from app.bootstrap.settings import settings
from app.infrastructure.ai.aliyun_tts import (
    AliyunSpeechSynthesizer,
    SpeechSynthesisError,
)
from app.infrastructure.ai.errors import ModelTimeBudgetExceeded
from app.infrastructure.security.experience_tokens import unseal
from app.infrastructure.storage.object_storage import storage

router = APIRouter(prefix="/guardian/experience", tags=["guardian-experience"])


class ExperienceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=2400)
    thread_id: UUID | None = None
    command_id: str | None = Field(default=None, min_length=1, max_length=128)
    state_token: str | None = Field(default=None, max_length=64000)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)
    mode: ExperienceMode = "student_guide"

    @model_validator(mode="after")
    def nonempty(self):
        self.content = self.content.strip()
        if not self.content and not self.attachment_keys:
            raise ValueError("a question or image is required")
        if self.thread_id and not self.command_id:
            raise ValueError("a threaded turn requires command_id")
        return self


def _state(token: str, principal: Principal, purpose: str) -> dict:
    try:
        return unseal(token, principal.user_id, purpose)
    except ValueError as error:
        raise HTTPException(409, {"code": "experience_expired"}) from error


_MENTOR_STAGES = {
    "tutoring-blueprint.extract": "read",
    "tutoring-blueprint.reread": "read",
    "tutoring-blueprint.primary": "solve",
    "tutoring-blueprint.ordinary": "solve",
    "tutoring-blueprint.backup": "solve",
    "guardian-mentor.explain": "explain",
}


@router.post("/turn", dependencies=[Depends(expose_turn_trace)])
def turn(
    body: ExperienceTurnRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    purpose = MENTOR_PURPOSE if body.mode == "guardian_explain" else "conversation"
    state = _state(body.state_token, principal, purpose) if body.state_token else {}
    def replay(session, thread):
        past = session.query(GuardianConversationTurn).filter_by(thread_id=thread.id, command_id=body.command_id).one_or_none()
        if past is None:
            return None
        if (past.content != body.content or past.attachments != body.attachment_keys or
                past.mode != body.mode or past.generation != thread.history_generation):
            raise HTTPException(409, "turn no longer matches request")
        return past.reply

    if body.thread_id:
        thread = thread_for(db, principal, body.thread_id)
        version = thread.version
        existing = replay(db, thread)
        if existing is None:
            previous = db.query(GuardianConversationTurn).filter_by(
                thread_id=thread.id, generation=thread.history_generation, mode=body.mode,
            ).order_by(GuardianConversationTurn.position.desc()).first()
            if not state.get("handoff"):
                state = previous.continuation if previous else {}

    if any(not owns_image(principal.user_id, key) or not storage.exists(key) for key in body.attachment_keys):
        raise HTTPException(400, "invalid experience attachment")
    default_prompt = (
        "请看这张图片，给出完整破题思路、核验结论与常见易错点解析。"
        if body.mode == "guardian_explain"
        else "请看这张图片，带我一步步理解。"
    )
    # The authenticated principal is a value object. Release its read transaction
    # before model I/O, including when the optional bank lookup is never used.
    bind = db.get_bind()
    db.close()

    def lookup(*, stem):
        with Session(bind) as reader:
            return GetProblemDossierQuery(reader).find_bank_ready(stem=stem)

    def invoke():
        try:
            if body.thread_id and existing is not None:
                return existing
            answer = experience_turn(
                guardian_id=principal.user_id,
                content=body.content or default_prompt,
                attachment_keys=body.attachment_keys,
                state=state,
                mode=body.mode,
                bank_lookup=lookup,
            )
            if body.thread_id:
                with Session(bind) as writer:
                    row = thread_for(writer, principal, body.thread_id, lock=True)
                    cached = replay(writer, row)
                    if cached is not None:
                        return cached
                    if row.version != version:
                        raise HTTPException(409, "conversation changed during generation")
                    row.version += 1
                    message_id = str(uuid4())
                    answer = {**answer, "message_id": message_id}
                    continuation = _state(answer["state_token"], principal, purpose) if answer.get("state_token") else state
                    writer.add(GuardianConversationTurn(
                        id=message_id, thread_id=row.id, generation=row.history_generation, position=row.version,
                        command_id=body.command_id, mode=body.mode, content=body.content,
                        attachments=body.attachment_keys, reply=answer, continuation=continuation,
                    ))
                    if row.title == "新对话" and body.content:
                        row.title = body.content[:40]
                    writer.commit()
            return answer
        except ModelTimeBudgetExceeded as error:
            raise HTTPException(503, {"code": "mentor_timeout"}) from error
        except MentorRateLimitExceeded as error:
            raise HTTPException(429, {"code": "mentor_rate_limited"}) from error

    if "text/event-stream" in request.headers.get("accept", ""):
        mentor = body.mode == "guardian_explain"
        return stream_reply(
            invoke, response, stages=_MENTOR_STAGES if mentor else GUIDE_STAGES,
            error_code="mentor_error" if mentor else "experience_error",
        )
    return invoke()


@router.post("/attachments/upload-url")
def upload_url(body: UploadUrlRequest, request: Request, principal: Annotated[Principal, Depends(current_guardian)]):
    extension = body.extension.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    if mime.get(extension) != body.content_type:
        raise HTTPException(400, "unsupported experience attachment")
    key = f"{media_prefix(principal.user_id)}{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key,
            "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speech_ref: str = Field(max_length=64000)
    rate: float = 1.0


@router.post("/speech")
def speech(body: SpeechRequest, principal: Annotated[Principal, Depends(current_guardian)]):
    lesson = _state(body.speech_ref, principal, "speech")
    rate = canonical_rate(body.rate)
    if rate is None:
        raise HTTPException(400, "unsupported speech rate")
    try:
        audio = AliyunSpeechSynthesizer().synthesize(text=lesson["source_text"], locale=lesson["locale"], rate=rate)
    except SpeechSynthesisError as error:
        raise HTTPException(503, {"code": "tts_error", "reason": error.code}) from error
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
