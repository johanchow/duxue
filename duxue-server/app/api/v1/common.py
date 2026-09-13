from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.bootstrap.settings import settings
from app.infrastructure.ai.asr import AsrConfigurationError, DashscopeRealtimeAsr, forward_asr_events
from app.infrastructure.persistence.database import Base, SessionLocal, engine, get_db
from app.api.deps import Principal, _bearer, current_device, current_guardian, current_guardian_or_ward, current_ward, guardian_principal_for_token
from app.infrastructure.persistence.models import (
    AnalysisProfile, BehaviorLabelConfig, BehaviorSegment, Device, Frame, FramePrediction,
    Guardian, GuardianWard, RefreshToken, WardRefreshToken, Report, User, Ward, WardCredential, WardInvite,
    Task, DailySchedule, PlanDraft, StudySession, StudySessionInterval, TutoringSession, TutoringMessage, SelfReview, FocusKit,
    AgentRun, AgentStreamEvent, AgentCheckpoint, AgentTrace, CompanionCommand, ConversationThread,
    LearningEvent, EpisodicMemory, EpisodicMemoryEvent, DerivedSignal, DerivedSignalEvent, LongTermProfile, OutboxEvent,
    now,
)
from app.api.schemas import (
    AnalyzeDayRequest, DeviceBind, FrameCreate, LabelCreate, LoginRequest, ProfileCreate,
    ProfilePatch, RefreshRequest, RegisterRequest, TokenPair, UploadUrlRequest, WardCreate,
    WardOut, WardPatch, WardBindRequest, AssignmentCreate, PlanDraft,
    MessageCreate, SessionFinish, SessionPause, SelfReviewCreate, TaskIntakeCleanup, TaskIntakeConfirm,
    TaskIntakeRequest, PlanIntakeCleanup, PlanIntakeConfirm, PlanIntakeRequest, CompanionTurnRequest, AgentRunCancelRequest, SignalChallengeRequest, ClientTelemetryBatch,
)
from app.infrastructure.security.tokens import create_access_token, hash_secret, random_token, token_hash, verify_secret
from app.application.commands.legacy_services import analyze_and_generate, corrected_time, make_invite_code, owned_ward, utc_bounds
from app.infrastructure.storage.object_storage import LocalStorage, storage
from app.application.commands.task_intake import TaskIntakeError, TaskIntakeService
from app.application.commands.plan_intake import PlanIntakeService
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.application.commands.memory import MemoryAccessDenied, SqlAlchemyMemoryCommandService
from app.infrastructure.observability.telemetry import record_asr_session, record_frame
from app.infrastructure.observability.client_telemetry import allow_batch, relay as relay_client_telemetry
from opentelemetry import trace
def _tokens(db: Session, guardian: Guardian) -> TokenPair:
    refresh = random_token()
    db.add(RefreshToken(
        guardian_id=guardian.id, token_hash=token_hash(refresh),
        expires_at=now() + timedelta(days=settings.refresh_token_days),
    ))
    db.commit()
    return TokenPair(
        access_token=create_access_token(user_id=guardian.id, role=guardian.role),
        refresh_token=refresh,
    )


def _ward_tokens(db: Session, credential: WardCredential) -> TokenPair:
    """Issue a Ward token pair tied to the currently active device session."""
    refresh = random_token()
    db.add(WardRefreshToken(
        ward_id=credential.ward_id,
        session_version=credential.session_version,
        token_hash=token_hash(refresh),
        expires_at=now() + timedelta(days=settings.refresh_token_days),
    ))
    db.commit()
    return TokenPair(
        access_token=create_access_token(
            user_id=credential.ward_id,
            role="ward",
            ward_session_version=credential.session_version,
        ),
        refresh_token=refresh,
    )


def _report(report: Report) -> dict:
    return {
        "id": report.id, "ward_id": report.ward_id, "report_date": report.report_date,
        "total_seconds": report.total_seconds, "label_breakdown": report.label_breakdown,
        "timeline_json": report.timeline_json, "profile_changed": report.profile_changed,
        "status": report.status, "generated_at": report.generated_at,
    }


def _ward_owned(principal: Principal, ward_id: str) -> None:
    if principal.user_id != ward_id:
        raise HTTPException(403, "ward may only access own data")


def open_session_for_task(db: Session, *, task_id: str) -> dict | None:
    query = db.query(StudySession).filter(StudySession.status.in_(("active", "paused"))).filter_by(task_id=task_id)
    row = query.order_by(StudySession.started_at.desc()).first()
    return None if row is None else {"id": row.id, "status": row.status, "active_seconds": row.active_seconds}
