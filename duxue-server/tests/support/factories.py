from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from sqlalchemy.orm import Session

from app.models import (
    DailySchedule,
    Device,
    Frame,
    Guardian,
    GuardianWard,
    LearningEvent,
    OutboxEvent,
    PlanDraft,
    SelfReview,
    StudySession,
    Task,
    User,
    Ward,
    WardCredential,
    now,
    uid,
)
from app.memory import LearningFactRecorded
from app.security import hash_secret, token_hash


def create_guardian(
    db: Session,
    *,
    name: str = "监护人",
    email: str | None = None,
    password: str = "password123",
    role: str = "guardian",
) -> Guardian:
    user = User(type="guardian")
    db.add(user)
    db.flush()
    guardian = Guardian(
        id=user.id,
        name=name,
        email=email or f"guardian_{uid()[:8]}@example.com",
        password_hash=hash_secret(password),
        role=role,
    )
    db.add(guardian)
    db.flush()
    return guardian


def create_ward(
    db: Session,
    *,
    guardian: Guardian | None = None,
    display_name: str = "小读",
    grade_stage: str = "primary",
    session_version: int = 1,
) -> Ward:
    user = User(type="ward")
    db.add(user)
    db.flush()
    ward = Ward(
        id=user.id,
        display_name=display_name,
        grade_stage=grade_stage,
    )
    db.add(ward)
    db.flush()
    db.add(WardCredential(ward_id=ward.id, session_version=session_version))
    if guardian:
        db.add(GuardianWard(guardian_id=guardian.id, ward_id=ward.id))
    db.flush()
    return ward


def create_device(
    db: Session,
    *,
    ward: Ward,
    raw_token: str | None = None,
    invite_code: str | None = None,
    status: str = "online",
) -> Device:
    device = Device(
        ward_id=ward.id,
        status=status,
        invite_code=invite_code,
        device_token_hash=token_hash(raw_token) if raw_token else None,
    )
    db.add(device)
    db.flush()
    return device


def create_task(
    db: Session,
    *,
    ward: Ward,
    title: str = "练习作业",
    planned_minutes: int = 30,
    status: str = "open",
    schedule_id: str | None = None,
    position: int | None = None,
) -> Task:
    task = Task(
        ward_id=ward.id,
        title=title,
        planned_minutes=planned_minutes,
        status=status,
        schedule_id=schedule_id,
        position=position,
    )
    db.add(task)
    db.flush()
    return task


def create_daily_schedule(
    db: Session,
    *,
    ward: Ward,
    schedule_date: date | None = None,
    status: str = "draft",
    version: int = 1,
) -> DailySchedule:
    day = schedule_date or datetime.now(timezone.utc).date()
    schedule = DailySchedule(
        ward_id=ward.id,
        schedule_date=day,
        status=status,
        version=version,
        confirmed_at=now() if status == "confirmed" else None,
    )
    db.add(schedule)
    db.flush()
    return schedule


def create_study_session(
    db: Session,
    *,
    ward: Ward,
    task: Task,
    status: str = "active",
) -> StudySession:
    session = StudySession(
        ward_id=ward.id,
        task_id=task.id,
        status=status,
    )
    db.add(session)
    db.flush()
    return session


def create_frame(
    db: Session,
    *,
    device: Device,
    ward: Ward,
    study_session: StudySession | None = None,
    captured_at: datetime | None = None,
    structured_fields: dict | None = None,
) -> Frame:
    at = captured_at or datetime.now(timezone.utc)
    frame = Frame(
        device_id=device.id,
        ward_id=ward.id,
        study_session_id=study_session.id if study_session else None,
        captured_at=at,
        structured_fields=structured_fields or {"hand_action": "右手握笔书写", "seat_status": "在座"},
        purge_after=at + timedelta(days=90),
    )
    db.add(frame)
    db.flush()
    return frame


def make_learning_fact(
    ward_id: str,
    *,
    event_type: str = "tutoring.hint_given",
    source_type: str = "test",
    source_id: str | None = None,
    source_version: int = 1,
    source: str = "system",
    visibility: str = "ward",
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> LearningFactRecorded:
    return LearningFactRecorded(
        ward_id=ward_id,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id or uid(),
        source_version=source_version,
        source=source,
        visibility=visibility,
        payload=payload or {},
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
