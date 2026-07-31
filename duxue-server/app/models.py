from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(30), default="self_hosted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Guardian(Base):
    __tablename__ = "user_guardians"
    id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="parent")


class Ward(Base):
    __tablename__ = "user_wards"
    id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_profile_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_profiles.id"), nullable=True)


class GuardianWard(Base):
    __tablename__ = "guardian_ward_relations"
    __table_args__ = (UniqueConstraint("guardian_id", "ward_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    guardian_id: Mapped[str] = mapped_column(ForeignKey("user_guardians.id", ondelete="CASCADE"))
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(30), default="guardian")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    guardian_id: Mapped[str] = mapped_column(ForeignKey("user_guardians.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalysisProfile(Base):
    __tablename__ = "analysis_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_guardians.id"))
    name: Mapped[str] = mapped_column(String(100))
    extra_observation_prompt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BehaviorLabelConfig(Base):
    __tablename__ = "behavior_label_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("analysis_profiles.id", ondelete="CASCADE"), index=True)
    label_name: Mapped[str] = mapped_column(String(100))
    field_prototypes: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id", ondelete="CASCADE"), index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id", ondelete="CASCADE"), index=True)
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), unique=True)
    behavior_label: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20), default="api")
    model_version: Mapped[str] = mapped_column(String(100), default="qwen3-vl-flash")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisBatch(Base):
    __tablename__ = "analysis_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    batch_date: Mapped[date] = mapped_column(Date)
    provider_batch_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BehaviorSegment(Base):
    __tablename__ = "behavior_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    seg_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seg_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    behavior_label: Mapped[str] = mapped_column(String(100))
    frame_count: Mapped[int] = mapped_column(Integer)
    confidence_avg: Mapped[float] = mapped_column(Float)


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("tenant_id", "ward_id", "report_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    ward_id: Mapped[str] = mapped_column(ForeignKey("user_wards.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0)
    label_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline_json: Mapped[list] = mapped_column(JSON, default=list)
    profile_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
