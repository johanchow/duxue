from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    email: str
    code: str = Field(pattern=r"^[0-9]{6}$")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("invalid email")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    code: str = Field(pattern=r"^[0-9]{6}$")


class EmailCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


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
    study_session_id: str | None = None


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
    invite_code: str = Field(pattern=r"^\d{6}$")

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

class SessionFinish(BaseModel):
    active_seconds: int = Field(ge=0)


class CompanionTurnRequest(BaseModel):
    """One Ward input to the deterministic companion entrypoint."""
    voice_display_text: str | None = Field(default=None, max_length=4000)
    content: str = Field(default="", max_length=4000)
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    thread_id: str | None = None
    expected_thread_version: int | None = Field(default=None, ge=0)
    route_hint: Literal["tutoring"] | None = None
    study_session_id: str | None = None
    tutoring_directive: str | None = Field(default=None, pattern=r"^(ask|attempt|understood|close)$")
    tutoring_intent: str | None = Field(default=None, pattern=r"^(pronunciation|compare_previous_image)$")
    attachment_keys: list[str] = Field(default_factory=list, max_length=8)
    structured_command: StructuredWardCommand | None = None

    @field_validator("command_id", "thread_id")
    @classmethod
    def valid_identifier(cls, value):
        from uuid import UUID
        return str(UUID(value)) if value is not None else None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class StructuredWardCommand(BaseModel):
    """A server-issued, allow-listed action; never an arbitrary tool call."""

    interaction_id: str = Field(min_length=1, max_length=200)
    command: Literal["sprint_command"]
    payload: dict[str, Any] = Field(default_factory=dict)


class WardAgentTurnRequest(CompanionTurnRequest):
    model_config = ConfigDict(extra="forbid")


class CompanionHistoryClearRequest(BaseModel):
    command_id: str = Field(min_length=32, max_length=36)

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        from uuid import UUID
        return str(UUID(value))


class AgentRunCancelRequest(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid4()))
    expected_thread_version: int | None = Field(default=None, ge=0)


class SignalChallengeRequest(BaseModel):
    statement: str = Field(min_length=1, max_length=1000)

    @field_validator("statement")
    @classmethod
    def strip_statement(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("statement must not be blank")
        return value


TelemetryPrimitive = str | int | float | bool


class ClientTelemetryEvent(BaseModel):
    """A privacy-filtered mobile telemetry record, never business content."""

    signal: str = Field(pattern=r"^(span|metric|event|log)$")
    name: str = Field(pattern=r"^app\.[a-z0-9_.-]{1,80}$")
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    turn_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    completed_ms: int | None = Field(default=None, gt=0, le=9_000_000_000_000)
    value: float | None = Field(default=None, ge=0, le=1_000_000)
    attributes: dict[str, TelemetryPrimitive] = Field(default_factory=dict, max_length=12)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def legacy_event_limits(self):
        if self.name != "app.conversation.completed":
            if self.duration_ms is not None and self.duration_ms > 120_000:
                raise ValueError("duration exceeds telemetry event limit")
            if self.completed_ms is not None or self.turn_id is not None:
                raise ValueError("turn fields require a conversation completion")
        return self


class ClientTelemetryBatch(BaseModel):
    events: list[ClientTelemetryEvent] = Field(min_length=1, max_length=20)


class SessionPause(BaseModel):
    active_seconds: int = Field(ge=0)


class StartCueCommand(BaseModel):
    command: str
    expected_version: int = Field(ge=1)
