from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Uuid, JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Guardian(Base):
    __tablename__ = "user_guardians"
    __table_args__ = (CheckConstraint("role IN ('admin', 'guardian')", name="ck_guardian_role"),)
    id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="guardian")


class Ward(Base):
    __tablename__ = "user_wards"
    id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    grade_stage: Mapped[str] = mapped_column(String(20), default="primary")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_profile_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_profiles.id"), nullable=True)


class GuardianWard(Base):
    __tablename__ = "guardian_ward_relations"
    __table_args__ = (UniqueConstraint("guardian_id", "ward_id"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    guardian_id: Mapped[str] = mapped_column(ForeignKey("user_guardians.id"))
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    guardian_id: Mapped[str] = mapped_column(ForeignKey("user_guardians.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class WardRefreshToken(Base):
    __tablename__ = "ward_refresh_tokens"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    session_version: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalysisProfile(Base):
    __tablename__ = "analysis_profiles"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_guardians.id"))
    name: Mapped[str] = mapped_column(String(100))
    extra_observation_prompt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BehaviorLabelConfig(Base):
    __tablename__ = "behavior_label_configs"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("analysis_profiles.id"), index=True)
    label_name: Mapped[str] = mapped_column(String(100))
    field_prototypes: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    device_type: Mapped[str] = mapped_column(String(30), default="android")
    device_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="offline")
    invite_code: Mapped[str | None] = mapped_column(String(6), nullable=True, index=True)
    invite_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invite_failures: Mapped[int] = mapped_column(Integer, default=0)
    capture_interval_seconds: Mapped[int] = mapped_column(Integer, default=15)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bound_server_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bound_elapsed_realtime: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Frame(Base):
    __tablename__ = "frames"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    # Sparse camera captures can happen outside an explicit study session.
    study_session_id: Mapped[str | None] = mapped_column(ForeignKey("study_sessions.id"), nullable=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    oss_key: Mapped[str | None] = mapped_column(String(500), nullable=True, unique=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_batches.id"), nullable=True)
    structured_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    training_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FramePrediction(Base):
    __tablename__ = "frame_predictions"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id"), unique=True)
    behavior_label: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="api")
    model_version: Mapped[str] = mapped_column(String(100), default="qwen3-vl-flash")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisBatch(Base):
    __tablename__ = "analysis_batches"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    batch_date: Mapped[date] = mapped_column(Date)
    provider_batch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BehaviorSegment(Base):
    __tablename__ = "behavior_segments"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    study_session_id: Mapped[str | None] = mapped_column(ForeignKey("study_sessions.id"), nullable=True, index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    seg_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seg_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    behavior_label: Mapped[str] = mapped_column(String(100))
    frame_count: Mapped[int] = mapped_column(Integer)
    confidence_avg: Mapped[float] = mapped_column(Float)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("ward_id", "report_date"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0)
    label_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline_json: Mapped[list] = mapped_column(JSON, default=list)
    profile_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# The daily-story tables deliberately keep the plan and its execution separate:
# guardians can supply work, but only a ward session can confirm/execute it.
class WardCredential(Base):
    __tablename__ = "ward_credentials"
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), primary_key=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class WardInvite(Base):
    __tablename__ = "ward_invites"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Task(Base):
    """A task exists once; schedule_id is null while it remains in the task pool."""
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("daily_schedules.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="guardian")
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class DailySchedule(Base):
    __tablename__ = "daily_schedules"
    __table_args__ = (UniqueConstraint("ward_id", "schedule_date"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    schedule_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class PlanDraft(Base):
    __tablename__ = "plan_drafts"
    __table_args__ = (UniqueConstraint("ward_id", "plan_date", name="uq_plan_draft_ward_date"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    base_schedule_version: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSON, default=list)
    pending_fields: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class StudySession(Base):
    __tablename__ = "study_sessions"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    # A session belongs either to a confirmed plan item or an assignment that
    # has not yet entered a plan.  Keeping the source explicit lets Ward start
    # a task from either part of the v3 home page without silently changing
    # their plan.
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_seconds: Mapped[int] = mapped_column(Integer, default=0)
    pause_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completion_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")

class StudySessionInterval(Base):
    __tablename__ = "study_session_intervals"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    study_session_id: Mapped[str] = mapped_column(ForeignKey("study_sessions.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class TutoringSession(Base):
    """A bounded AI dialogue inside a study session; a session may have no dialogue."""
    __tablename__ = "tutoring_sessions"
    __table_args__ = (UniqueConstraint("study_session_id", name="uq_tutoring_session_study_session"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    study_session_id: Mapped[str] = mapped_column(ForeignKey("study_sessions.id"), index=True)
    subject: Mapped[str | None] = mapped_column(String(40), nullable=True)
    question_type: Mapped[str] = mapped_column(String(30), default="general")
    question_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TutoringMessage(Base):
    __tablename__ = "tutoring_messages"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    tutoring_session_id: Mapped[str] = mapped_column(ForeignKey("tutoring_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    interest_signal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_stuck_point: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SelfReview(Base):
    __tablename__ = "self_reviews"
    __table_args__ = (UniqueConstraint("ward_id", "review_date"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    review_date: Mapped[date] = mapped_column(Date, index=True)
    feeling: Mapped[str] = mapped_column(String(40))
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline_json: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FocusKit(Base):
    __tablename__ = "focus_kits"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    review_date: Mapped[date] = mapped_column(Date, index=True)
    advice: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# These tables are runtime audit and recovery metadata.  They deliberately do
# not replace domain aggregates, learning events, or LangGraph's graph-state
# checkpointer.
class ConversationThread(Base):
    __tablename__ = "conversation_threads"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    # Kept as a validated reference instead of an FK to avoid a circular
    # thread/run dependency; AgentRun.thread_id remains the authoritative FK.
    focus_run_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("thread_id", "run_ref", name="uq_agent_run_thread_ref"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    agent_type: Mapped[str] = mapped_column(String(20), index=True)
    # A domain aggregate reference (for example tutoring_session:<uuid>), not
    # a copy of that aggregate or its chat history.
    run_ref: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    current_turn_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str] = mapped_column(String(40), default="v1")
    context_refs: Mapped[list] = mapped_column(JSON, default=list)
    graph_checkpoint_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graph_version: Mapped[str] = mapped_column(String(40), default="v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanionCommand(Base):
    """Idempotency fence for a Ward's companion command."""

    __tablename__ = "companion_commands"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_threads.id"), nullable=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanionMessage(Base):
    """Immutable, Ward-visible transcript journal; never an aggregate."""

    __tablename__ = "companion_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "thread_version", name="uq_companion_messages_thread_version"),
        UniqueConstraint("ward_id", "command_id", "author_type", name="uq_companion_messages_ward_command_author"),
        UniqueConstraint("run_id", "turn_id", "attempt", "author_type", name="uq_companion_messages_run_turn_attempt_author"),
        CheckConstraint("author_type IN ('ward', 'companion')", name="ck_companion_message_author"),
        Index("idx_companion_messages_ward_thread_version", "ward_id", "thread_id", "thread_version"),
    )
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"))
    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    command_id: Mapped[str] = mapped_column(ForeignKey("companion_commands.id"))
    turn_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thread_version: Mapped[int] = mapped_column(Integer)
    author_type: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    attachment_refs: Mapped[list] = mapped_column(JSON, default=list)
    interaction_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentStreamEvent(Base):
    """Replayable, redacted Ward-facing stream records for one Run attempt."""

    __tablename__ = "agent_stream_events"
    __table_args__ = (UniqueConstraint("run_id", "attempt", "sequence", name="uq_agent_stream_sequence"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str] = mapped_column(String(40), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "checkpoint_ref", name="uq_agent_checkpoint_run_ref"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    checkpoint_ref: Mapped[str] = mapped_column(String(255))
    graph_version: Mapped[str] = mapped_column(String(40))
    state_digest: Mapped[str] = mapped_column(String(128))
    settlement_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentTrace(Base):
    __tablename__ = "agent_traces"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    thread_id: Mapped[str] = mapped_column(ForeignKey("conversation_threads.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True, index=True)
    route_target: Mapped[str] = mapped_column(String(20))
    route_mode: Mapped[str] = mapped_column(String(20))
    route_reason: Mapped[str] = mapped_column(String(120))
    context_refs: Mapped[list] = mapped_column(JSON, default=list)
    # Redacted ContextEnvelope metadata only; never chain-of-thought or raw chat.
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (UniqueConstraint("source_type", "source_id", "event_type", "source_version", name="uq_learning_event_source"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    source_version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(20), default="system")
    retention_policy: Mapped[str] = mapped_column(String(40), default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EpisodicMemory(Base):
    __tablename__ = "episodic_memories"
    __table_args__ = (UniqueConstraint("memory_type", "aggregate_ref", "aggregate_version", name="uq_episodic_memory_aggregate"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    memory_type: Mapped[str] = mapped_column(String(80), default="legacy", index=True)
    aggregate_ref: Mapped[str] = mapped_column(String(120), default="legacy")
    aggregate_version: Mapped[int] = mapped_column(Integer, default=1)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    summary: Mapped[str] = mapped_column(Text)
    raw_cues: Mapped[dict] = mapped_column(JSON, default=dict)
    decay_weight: Mapped[float] = mapped_column(Float, default=1.0)
    hot_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(40), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DerivedSignal(Base):
    __tablename__ = "derived_signals"
    __table_args__ = (UniqueConstraint("ward_id", "signal_type", "scope", "dimension_key", name="uq_derived_signal_identity"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String(80))
    subject: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scope: Mapped[str] = mapped_column(String(20))
    dimension_key: Mapped[str] = mapped_column(String(120), default="")
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    statement: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    policy_version: Mapped[str] = mapped_column(String(40), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class EpisodicMemoryEvent(Base):
    __tablename__ = "episodic_memory_events"
    __table_args__ = (UniqueConstraint("episodic_memory_id", "learning_event_id", name="uq_episodic_memory_event"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    episodic_memory_id: Mapped[str] = mapped_column(ForeignKey("episodic_memories.id"))
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"))
    role: Mapped[str] = mapped_column(String(20), default="supporting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DerivedSignalEvent(Base):
    __tablename__ = "derived_signal_events"
    __table_args__ = (UniqueConstraint("derived_signal_id", "learning_event_id", "role", name="uq_derived_signal_event_role"),)
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=uid)
    derived_signal_id: Mapped[str] = mapped_column(ForeignKey("derived_signals.id"))
    learning_event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id"))
    role: Mapped[str] = mapped_column(String(20), default="support")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LongTermProfile(Base):
    __tablename__ = "long_term_profiles"
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id"), primary_key=True)
    focus_endurance_baseline_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    focus_endurance_baseline_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    subject_difficulty_map: Mapped[dict] = mapped_column(JSON, default=dict)
    mature_interest_radar: Mapped[dict] = mapped_column(JSON, default=dict)
    learning_strategy_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    planning_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    self_regulation_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    habit_patterns: Mapped[dict] = mapped_column(JSON, default=dict)
    parental_interaction_pref: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
