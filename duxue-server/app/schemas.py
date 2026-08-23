from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class WardCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    grade_stage: str = Field(pattern=r"^(primary|middle|high)$")
    notes: str | None = None


class WardPatch(BaseModel):
    display_name: str | None = None
    notes: str | None = None
    grade_stage: str | None = Field(default=None, pattern=r"^(primary|middle|high)$")
    analysis_profile_id: str | None = None


class WardOut(ORMModel):
    id: str
    display_name: str
    grade_stage: str
    notes: str | None
    analysis_profile_id: str | None


class DeviceBind(BaseModel):
    invite_code: str = Field(min_length=6, max_length=6)
    elapsed_realtime: int | None = None


class FrameCreate(BaseModel):
    oss_key: str
    captured_at: datetime
    elapsed_realtime: int | None = None


class UploadUrlRequest(BaseModel):
    content_type: str = "image/jpeg"
    extension: str = "jpg"


class ProfileCreate(BaseModel):
    name: str
    extra_observation_prompt: str = ""


class ProfilePatch(BaseModel):
    name: str | None = None
    extra_observation_prompt: str | None = None


class LabelCreate(BaseModel):
    label_name: str
    field_prototypes: dict[str, list[str]] = Field(default_factory=dict)
    priority: int = 0
    is_active: bool = True


class AnalyzeDayRequest(BaseModel):
    ward_id: str
    report_date: date
    results: dict[str, dict[str, Any]] = Field(default_factory=dict)

class WardBindRequest(BaseModel):
    invite_code: str = Field(min_length=8, max_length=8)
    pin: str = Field(pattern=r"^\d{4,8}$")

class WardLoginRequest(BaseModel):
    ward_id: str
    pin: str = Field(pattern=r"^\d{4,8}$")

class AssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    details: str | None = None
    due_date: date | None = None


class TaskCandidate(BaseModel):
    ward_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    details: str | None = Field(default=None, max_length=4000)
    due_date: date | None = None


class TaskIntakeMessage(BaseModel):
    role: str = Field(pattern=r"^(guardian|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class TaskIntakeRequest(BaseModel):
    content: str = Field(default="", max_length=4000)
    history: list[TaskIntakeMessage] = Field(default_factory=list, max_length=20)
    tasks: list[TaskCandidate] = Field(default_factory=list, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class TaskIntakeConfirm(BaseModel):
    tasks: list[TaskCandidate] = Field(min_length=1, max_length=30)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)


class TaskIntakeCleanup(BaseModel):
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)

class PlanDraft(BaseModel):
    plan_date: date
    items: list[dict[str, Any]] = Field(min_length=1)

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

class SessionFinish(BaseModel):
    active_seconds: int = Field(ge=0)

class SelfReviewCreate(BaseModel):
    feeling: str = Field(min_length=1, max_length=40)
    reflection: str | None = Field(default=None, max_length=2000)
    timeline_json: list[dict[str, Any]] = Field(default_factory=list)
