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
    tenant_name: str | None = None

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
    notes: str | None = None


class WardPatch(BaseModel):
    display_name: str | None = None
    notes: str | None = None
    analysis_profile_id: str | None = None


class WardOut(ORMModel):
    id: str
    display_name: str
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
