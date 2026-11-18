"""Authenticated adult experience, isolated from every Ward aggregate."""
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import Principal, current_guardian, get_db
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
from app.infrastructure.security.experience_tokens import unseal
from app.infrastructure.storage.object_storage import storage

router = APIRouter(prefix="/guardian/experience", tags=["guardian-experience"])


class ExperienceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=2400)
    state_token: str | None = Field(default=None, max_length=64000)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)
    mode: ExperienceMode = "student_guide"

    @model_validator(mode="after")
    def nonempty(self):
        self.content = self.content.strip()
        if not self.content and not self.attachment_keys:
            raise ValueError("a question or image is required")
        return self


def _state(token: str, principal: Principal, purpose: str) -> dict:
    try:
        return unseal(token, principal.user_id, purpose)
    except ValueError as error:
        raise HTTPException(409, {"code": "experience_expired"}) from error


@router.post("/turn")
def turn(
    body: ExperienceTurnRequest,
    principal: Annotated[Principal, Depends(current_guardian)],
    db: Annotated[Session, Depends(get_db)],
):
    purpose = MENTOR_PURPOSE if body.mode == "guardian_explain" else "conversation"
    state = _state(body.state_token, principal, purpose) if body.state_token else {}
    if any(not owns_image(principal.user_id, key) or not storage.exists(key) for key in body.attachment_keys):
        raise HTTPException(400, "invalid experience attachment")
    default_prompt = (
        "请看这张图片，给出完整破题思路、核验结论与常见易错点解析。"
        if body.mode == "guardian_explain"
        else "请看这张图片，带我一步步理解。"
    )
    try:
        return experience_turn(
            guardian_id=principal.user_id,
            content=body.content or default_prompt,
            attachment_keys=body.attachment_keys,
            state=state,
            mode=body.mode,
            bank_lookup=GetProblemDossierQuery(db).find_bank_ready,
        )
    except MentorRateLimitExceeded as error:
        raise HTTPException(429, {"code": "mentor_rate_limited"}) from error


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
