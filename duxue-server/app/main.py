from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .asr import AsrConfigurationError, DashscopeRealtimeAsr, forward_asr_events
from .database import Base, SessionLocal, engine, get_db
from .dependencies import Principal, _bearer, current_device, current_guardian, current_guardian_or_ward, current_ward, guardian_principal_for_token
from .models import (
    AnalysisProfile, BehaviorLabelConfig, BehaviorSegment, Device, Frame, FramePrediction,
    Guardian, GuardianWard, RefreshToken, Report, User, Ward, WardCredential, WardInvite,
    Task, DailySchedule, PlanDraft, StudySession, StudySessionInterval, TutoringSession, TutoringMessage, SelfReview, FocusKit,
    AgentRun, AgentStreamEvent, AgentCheckpoint, AgentTrace, CompanionCommand, ConversationThread,
    LearningEvent, EpisodicMemory, EpisodicMemoryEvent, DerivedSignal, DerivedSignalEvent, LongTermProfile, OutboxEvent,
    WardCredential, WardInvite, now,
)
from .schemas import (
    AnalyzeDayRequest, DeviceBind, FrameCreate, LabelCreate, LoginRequest, ProfileCreate,
    ProfilePatch, RefreshRequest, RegisterRequest, TokenPair, UploadUrlRequest, WardCreate,
    WardOut, WardPatch, WardBindRequest, AssignmentCreate, PlanDraft,
    MessageCreate, SessionFinish, SessionPause, SelfReviewCreate, TaskIntakeCleanup, TaskIntakeConfirm,
    TaskIntakeRequest, PlanIntakeCleanup, PlanIntakeConfirm, PlanIntakeRequest, CompanionTurnRequest, AgentRunCancelRequest, SignalChallengeRequest, ClientTelemetryBatch,
)
from .security import create_access_token, hash_secret, random_token, token_hash, verify_secret
from .services import analyze_and_generate, corrected_time, make_invite_code, owned_ward, utc_bounds
from .storage import LocalStorage, storage
from .task_intake import TaskIntakeError, TaskIntakeService
from .plan_intake import PlanIntakeService
from .integration_events import publish_learning_fact
from .ai_runtime.companion_coordinator import CompanionCoordinator
from .memory import MemoryAccessDenied, SqlAlchemyMemoryCommandService
from .observability import configure_observability, record_frame
from .client_telemetry import allow_batch, relay as relay_client_telemetry
from opentelemetry import trace


app = FastAPI(title="读学 Server", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allow_origins),
    allow_methods=["*"], allow_headers=["*"],
)
configure_observability(component=os.getenv("OTEL_SERVICE_COMPONENT", "api"), app=app, engine=engine)


@app.on_event("startup")
def startup() -> None:
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)


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


def _report(report: Report) -> dict:
    return {
        "id": report.id, "ward_id": report.ward_id, "report_date": report.report_date,
        "total_seconds": report.total_seconds, "label_breakdown": report.label_breakdown,
        "timeline_json": report.timeline_json, "profile_changed": report.profile_changed,
        "status": report.status, "generated_at": report.generated_at,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/telemetry/client-events", status_code=202)
def relay_mobile_telemetry(
    body: ClientTelemetryBatch,
    principal: Principal = Depends(current_guardian_or_ward),
):
    trace.get_current_span().set_attribute("duxue.component", "telemetry-relay")
    if not allow_batch(principal.user_id, len(body.events)):
        raise HTTPException(429, "telemetry rate limit exceeded")
    try:
        return {"accepted": relay_client_telemetry(body.events)}
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


def _ward_owned(principal: Principal, ward_id: str) -> None:
    if principal.user_id != ward_id:
        raise HTTPException(403, "ward may only access own data")


@app.websocket("/ws/asr/transcribe")
async def transcribe_voice(websocket: WebSocket) -> None:
    """Authenticate a Guardian and proxy one hold-to-talk turn to DashScope."""
    db = SessionLocal()
    provider = None
    forward_task = None
    try:
        try:
            principal = current_guardian_or_ward(websocket.headers.get("authorization"), db)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        start = await websocket.receive_json()
        if start.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "start is required"})
            await websocket.close(code=1008)
            return

        provider = await DashscopeRealtimeAsr.connect()
        await websocket.send_json({"type": "ready", "max_seconds": settings.asr_max_record_seconds})
        forward_task = asyncio.create_task(forward_asr_events(provider, websocket.send_json))
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=settings.asr_max_record_seconds)
            except TimeoutError:
                await websocket.send_json({"type": "error", "message": "recording exceeded the maximum duration"})
                return
            if message.get("bytes") is not None:
                await provider.send_audio(message["bytes"])
                continue
            if message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "cancel":
                    return
                if command.get("type") == "commit":
                    await provider.commit()
                    await forward_task
                    return
                await websocket.send_json({"type": "error", "message": "unsupported ASR command"})
                return
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except AsrConfigurationError as error:
        await websocket.send_json({"type": "error", "message": str(error)})
    except Exception:
        await websocket.send_json({"type": "error", "message": "voice transcription is temporarily unavailable"})
    finally:
        if forward_task and not forward_task.done():
            forward_task.cancel()
        if provider:
            await provider.finish()
            await provider.close()
        db.close()


@app.post("/wards/{ward_id}/login-invite", status_code=201)
def ward_login_invite(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    code = None
    for _ in range(10):
        candidate = f"{secrets.randbelow(1_000_000):06d}"
        if db.query(WardInvite).filter_by(code=candidate).one_or_none() is None:
            code = candidate
            break
    if code is None:
        raise HTTPException(503, "unable to generate a binding code")
    row = WardInvite(ward_id=ward_id, code=code, expires_at=now() + timedelta(minutes=10))
    db.add(row); db.commit()
    return {"ward_id": ward_id, "invite_code": code, "expires_at": row.expires_at}

@app.post("/ward-auth/bind")
def ward_bind(body: WardBindRequest, db: Session = Depends(get_db)):
    invite = db.query(WardInvite).filter(WardInvite.code == body.invite_code.upper(), WardInvite.consumed_at.is_(None)).one_or_none()
    if invite is None or invite.expires_at.replace(tzinfo=timezone.utc) < now():
        raise HTTPException(400, "invite code is invalid or expired")
    credential = db.get(WardCredential, invite.ward_id)
    if credential is None:
        credential = WardCredential(ward_id=invite.ward_id); db.add(credential)
    else:
        credential.session_version += 1
    invite.consumed_at = now(); db.commit()
    return {"ward_id": invite.ward_id, "access_token": create_access_token(user_id=invite.ward_id, role="ward", ward_session_version=credential.session_version), "token_type": "bearer"}

@app.get("/ward/profile")
def ward_profile(principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    ward = db.get(Ward, principal.user_id)
    guardians = db.query(Guardian).join(GuardianWard, GuardianWard.guardian_id == Guardian.id).filter(GuardianWard.ward_id == principal.user_id).order_by(Guardian.name).all()
    return {"id": ward.id, "display_name": ward.display_name, "guardians": [{"id": guardian.id, "name": guardian.name} for guardian in guardians]}


@app.post("/companion/turn")
def companion_turn(body: CompanionTurnRequest, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    """Create or continue exactly one controlled companion domain Run.

    This foundation endpoint intentionally returns routing/context metadata only;
    the selected domain workflow will own Ward-facing streaming output.
    """
    try:
        result = CompanionCoordinator(db).handle(
            ward_id=principal.user_id,
            content=body.content,
            thread_id=body.thread_id,
            expected_thread_version=body.expected_thread_version,
            route_hint=body.route_hint,
            command_id=body.command_id,
            planning_items=body.planning_items,
            planning_confirm=body.planning_confirm,
            study_session_id=body.study_session_id,
            tutoring_directive=body.tutoring_directive,
            review_date=body.review_date,
            review_feeling=body.review_feeling,
            review_reflection=body.review_reflection,
            adopt_focus_kit=body.adopt_focus_kit,
        )
        return result.model_dump()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@app.post("/companion/runs/{run_id}/cancel")
def cancel_companion_run(
    run_id: str,
    body: AgentRunCancelRequest,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    try:
        return CompanionCoordinator(db).cancel(
            ward_id=principal.user_id,
            run_id=run_id,
            command_id=body.command_id,
            expected_thread_version=body.expected_thread_version,
        ).model_dump()
    except HTTPException:
        db.rollback()
        raise


@app.get("/companion/runs/{run_id}/events")
def replay_companion_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    attempt: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    """Replay redacted events for the current or requested Run attempt.

    The client treats this as SSE replay, not a write model.  A stale attempt
    is rejected so an old handoff cannot be appended to the current UI.
    """
    run = db.get(AgentRun, run_id)
    if run is None or run.ward_id != principal.user_id:
        raise HTTPException(404, "agent run not found")
    selected_attempt = attempt or run.attempt
    if selected_attempt != run.attempt:
        raise HTTPException(409, "requested attempt is no longer current")
    events = db.query(AgentStreamEvent).filter(
        AgentStreamEvent.run_id == run_id,
        AgentStreamEvent.attempt == selected_attempt,
        AgentStreamEvent.sequence > after_sequence,
    ).order_by(AgentStreamEvent.sequence).all()

    def stream():
        for event in events:
            payload = {
                "thread_id": run.thread_id,
                "run_id": run.id,
                "attempt": selected_attempt,
                "sequence": event.sequence,
                "policy_version": event.policy_version,
                "payload": event.payload,
            }
            yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/memory/signals/{signal_id}/challenge")
def challenge_memory_signal(
    signal_id: str,
    body: SignalChallengeRequest,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    """Allow a Ward to correct a derived conclusion with counterevidence."""
    try:
        service = SqlAlchemyMemoryCommandService(db)
        signal = service.challenge_signal(signal_id, principal.user_id, body.statement)
        service.rebuild_long_term_profile(principal.user_id)
        db.commit()
        return {"id": signal.id, "status": signal.status}
    except MemoryAccessDenied:
        db.rollback()
        raise HTTPException(404, "signal not found")

def _task_intake_wards(db: Session, guardian_id: str) -> list[dict]:
    rows = db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(
        GuardianWard.guardian_id == guardian_id,
    ).order_by(Ward.display_name).all()
    return [{"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage} for ward in rows]


def _task_intake_attachments(guardian_id: str, keys: list[str]) -> None:
    prefix = f"guardian/{guardian_id}/task-intake/"
    if any(not key.startswith(prefix) or not storage.exists(key) for key in keys):
        raise HTTPException(400, "invalid task intake attachment")


def _plan_intake_attachments(ward_id: str, keys: list[str]) -> None:
    prefix = f"ward/{ward_id}/plan-intake/"
    if any(not key.startswith(prefix) or not storage.exists(key) for key in keys):
        raise HTTPException(400, "invalid plan intake attachment")


@app.post("/task-intake/upload-url")
def task_intake_upload_url(body: UploadUrlRequest, request: Request, principal: Principal = Depends(current_guardian)):
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    if not body.content_type.startswith("image/"):
        raise HTTPException(400, "unsupported image content type")
    key = f"guardian/{principal.user_id}/task-intake/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@app.post("/task-intake/respond")
def respond_to_task_intake(body: TaskIntakeRequest, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    wards = _task_intake_wards(db, principal.user_id)
    if not wards:
        raise HTTPException(400, "create a ward before sending tasks")
    try:
        return TaskIntakeService().respond(wards=wards, request=body).model_dump(mode="json")
    except TaskIntakeError as error:
        raise HTTPException(502, str(error)) from error


@app.post("/task-intake/confirm", status_code=201)
def confirm_task_intake(body: TaskIntakeConfirm, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    try:
        for task in body.tasks:
            owned_ward(db, principal.user_id, task.ward_id)
        rows = [Task(ward_id=task.ward_id, title=task.title, details=task.details, due_date=task.due_date) for task in body.tasks]
        db.add_all(rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for key in body.attachment_keys:
        storage.delete(key)
    return {"assignments": [{"id": row.id, "ward_id": row.ward_id, "title": row.title} for row in rows]}


@app.post("/task-intake/cleanup", status_code=204)
def cleanup_task_intake(body: TaskIntakeCleanup, principal: Principal = Depends(current_guardian)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    for key in body.attachment_keys:
        storage.delete(key)


@app.post("/wards/{ward_id}/plan-intake/upload-url")
def plan_intake_upload_url(ward_id: str, body: UploadUrlRequest, request: Request, principal: Principal = Depends(current_ward)):
    _ward_owned(principal, ward_id)
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    if not body.content_type.startswith("image/"):
        raise HTTPException(400, "unsupported image content type")
    key = f"ward/{ward_id}/plan-intake/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@app.post("/wards/{ward_id}/plans/{plan_date}/intake")
def respond_to_plan_intake(ward_id: str, plan_date: date, body: PlanIntakeRequest, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    # The API stores schedule dates against the server's UTC clock; using the
    # host-local date here made the same UTC request fail around midnight.
    if plan_date != now().date():
        raise HTTPException(400, "plan intake is only available for today")
    _plan_intake_attachments(ward_id, body.attachment_keys)
    ward = db.get(Ward, ward_id)
    tasks = db.query(Task).filter_by(ward_id=ward_id).filter(Task.status != "completed").all()
    try:
        return PlanIntakeService().respond(
            ward={"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage},
            tasks=[{"id": task.id, "title": task.title, "details": task.details} for task in tasks],
            request=body,
        ).model_dump(mode="json")
    except TaskIntakeError as error:
        raise HTTPException(502, str(error)) from error


@app.post("/wards/{ward_id}/plans/{plan_date}/intake/confirm", status_code=201)
def confirm_plan_intake(ward_id: str, plan_date: date, body: PlanIntakeConfirm, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if plan_date != now().date():
        raise HTTPException(400, "plan intake is only available for today")
    _plan_intake_attachments(ward_id, body.attachment_keys)
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is not None:
        existing = db.query(Task).filter_by(schedule_id=plan.id).all()
        if any(item.status != "pending" for item in existing):
            raise HTTPException(409, "a started or completed plan cannot be changed")
    try:
        if any(item.new_task == (item.assignment_id is not None) for item in body.items):
            raise HTTPException(400, "plan task source is invalid")
        assignment_ids = {item.assignment_id for item in body.items if item.assignment_id}
        owned = db.query(Task).filter(Task.id.in_(assignment_ids)).filter_by(ward_id=ward_id).all() if assignment_ids else []
        if {row.id for row in owned} != assignment_ids:
            raise HTTPException(400, "plan contains a task that does not belong to this ward")
        if plan is None:
            plan = DailySchedule(ward_id=ward_id, schedule_date=plan_date)
            db.add(plan)
            db.flush()
        else:
            db.query(Task).filter_by(schedule_id=plan.id).update({Task.schedule_id: None, Task.position: None, Task.planned_minutes: None})
        for position, item in enumerate(body.items):
            assignment_id = item.assignment_id
            if item.new_task:
                created = Task(ward_id=ward_id, title=item.title, details=item.details, source="ward")
                db.add(created)
                db.flush()
                assignment_id = created.id
            task = db.get(Task, assignment_id)
            task.schedule_id, task.position, task.planned_minutes = plan.id, position, item.planned_minutes
        plan.status = "confirmed"
        plan.confirmed_at = now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    for key in body.attachment_keys:
        storage.delete(key)
    return {"id": plan.id, "status": plan.status}


@app.post("/wards/{ward_id}/plan-intake/cleanup", status_code=204)
def cleanup_plan_intake(ward_id: str, body: PlanIntakeCleanup, principal: Principal = Depends(current_ward)):
    _ward_owned(principal, ward_id)
    _plan_intake_attachments(ward_id, body.attachment_keys)
    for key in body.attachment_keys:
        storage.delete(key)


@app.post("/wards/{ward_id}/assignments", status_code=201)
def create_assignment(ward_id: str, body: AssignmentCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id); row = Task(ward_id=ward_id, **body.model_dump()); db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "title": row.title, "status": row.status, "source": row.source}

@app.get("/wards/{ward_id}/assignments")
def assignments(ward_id: str, principal: Principal = Depends(current_guardian_or_ward), db: Session = Depends(get_db)):
    if principal.role == "ward": _ward_owned(principal, ward_id)
    else: owned_ward(db, principal.user_id, ward_id)
    rows = db.query(Task).filter_by(ward_id=ward_id).filter(Task.status != "completed").all()
    return [{"id": x.id, "title": x.title, "details": x.details, "due_date": x.due_date, "status": x.status,
             "session": _open_session(db, task_id=x.id)} for x in rows]

@app.put("/wards/{ward_id}/plans/{plan_date}")
def save_plan(ward_id: str, plan_date: date, body: PlanDraft, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if body.plan_date != plan_date: raise HTTPException(400, "date mismatch")
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: plan = DailySchedule(ward_id=ward_id, schedule_date=plan_date); db.add(plan); db.flush()
    if plan.status == "confirmed": raise HTTPException(409, "confirmed plan cannot be changed")
    db.query(Task).filter_by(schedule_id=plan.id).update({Task.schedule_id: None, Task.position: None, Task.planned_minutes: None})
    for position, item in enumerate(body.items):
        task = db.get(Task, item.get("assignment_id")) if item.get("assignment_id") else None
        if task is None:
            task = Task(ward_id=ward_id, title=item.get("title", "学习任务"), source="ward")
            db.add(task); db.flush()
        task.schedule_id, task.position, task.planned_minutes = plan.id, position, int(item.get("planned_minutes", 30))
    db.commit(); return {"id": plan.id, "status": plan.status}

@app.post("/wards/{ward_id}/plans/{plan_date}/confirm")
def confirm_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    plan.status = "confirmed"; plan.confirmed_at = now(); db.commit(); return {"id": plan.id, "status": plan.status}

@app.get("/wards/{ward_id}/plans/{plan_date}")
def get_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_guardian_or_ward), db: Session = Depends(get_db)):
    if principal.role == "ward": _ward_owned(principal, ward_id)
    else: owned_ward(db, principal.user_id, ward_id)
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    items = db.query(Task).filter_by(schedule_id=plan.id).order_by(Task.position)
    return {"id": plan.id, "status": plan.status, "items": [{"id": x.id, "assignment_id": x.id, "title": x.title, "planned_minutes": x.planned_minutes, "status": x.status,
             "session": _open_session(db, task_id=x.id)} for x in items]}


def _open_session(db: Session, *, task_id: str) -> dict | None:
    query = db.query(StudySession).filter(StudySession.status.in_(("active", "paused"))).filter_by(task_id=task_id)
    row = query.order_by(StudySession.started_at.desc()).first()
    return None if row is None else {"id": row.id, "status": row.status, "active_seconds": row.active_seconds}

@app.post("/plan-items/{item_id}/sessions", status_code=201)
def start_session(item_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    item = db.get(Task, item_id); plan = db.get(DailySchedule, item.schedule_id) if item and item.schedule_id else None
    if plan is None or plan.ward_id != principal.user_id: raise HTTPException(404, "plan task not found")
    active = _open_session(db, task_id=item.id)
    if active: return active
    row = StudySession(ward_id=principal.user_id, task_id=item.id); item.status="active"; db.add(row); db.flush(); db.add(StudySessionInterval(study_session_id=row.id))
    publish_learning_fact(db, ward_id=row.ward_id, event_type="study_session.started", source_type="study_session", source_id=row.id, payload={"task_id": row.task_id})
    db.commit(); return {"id": row.id, "status": row.status, "active_seconds": 0}


@app.post("/assignments/{assignment_id}/sessions", status_code=201)
def start_assignment_session(assignment_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    assignment = db.get(Task, assignment_id)
    if assignment is None or assignment.ward_id != principal.user_id or assignment.status == "completed": raise HTTPException(404, "assignment not found")
    active = _open_session(db, task_id=assignment.id)
    if active: return active
    row = StudySession(ward_id=principal.user_id, task_id=assignment.id); assignment.status="active"; db.add(row); db.flush(); db.add(StudySessionInterval(study_session_id=row.id))
    publish_learning_fact(db, ward_id=row.ward_id, event_type="study_session.started", source_type="study_session", source_id=row.id, payload={"task_id": row.task_id})
    db.commit(); return {"id": row.id, "status": row.status, "active_seconds": 0}


@app.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "paused": raise HTTPException(404, "paused session not found")
    session.status="active"; session.version += 1; session.last_activity_at=now()
    db.get(Task, session.task_id).status="active"; db.add(StudySessionInterval(study_session_id=session.id))
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.resumed", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id})
    db.commit(); return {"id": session.id, "status": session.status, "active_seconds": session.active_seconds}


@app.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, body: SessionPause, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "active": raise HTTPException(404, "active session not found")
    interval = db.query(StudySessionInterval).filter_by(study_session_id=session.id, ended_at=None).one()
    interval.ended_at=now(); interval.end_reason="paused"; interval.active_seconds=max(0, body.active_seconds-session.active_seconds)
    session.status="paused"; session.active_seconds=body.active_seconds; session.pause_count += 1; session.version += 1; session.last_activity_at=interval.ended_at
    db.get(Task, session.task_id).status="paused"
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.paused", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id, "active_seconds": session.active_seconds})
    db.commit(); return {"id": session.id, "status": session.status, "active_seconds": session.active_seconds}

@app.post("/sessions/{session_id}/messages")
def tutor(session_id: str, body: MessageCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    tutoring_session = db.query(TutoringSession).filter_by(study_session_id=session_id).one_or_none()
    if tutoring_session is None:
        tutoring_session = TutoringSession(ward_id=session.ward_id, study_session_id=session_id, question_summary=body.content, model_name="fallback-socratic-v1")
        db.add(tutoring_session); db.flush()
    question = TutoringMessage(tutoring_session_id=tutoring_session.id, role="ward", content=body.content, is_stuck_point=True)
    db.add(question); db.flush()
    publish_learning_fact(db, ward_id=session.ward_id, event_type="tutoring.stuck_point_recorded", source_type="tutoring_message", source_id=question.id, payload={"study_session_id": session.id, "tutoring_session_id": tutoring_session.id})
    # Model routing remains injectable; this safe fallback keeps an unavailable provider from blocking study.
    answer = "先别急着找答案。你能说说题目已知什么、要解决什么吗？把第一步写出来，我们一起检查。"
    db.add(TutoringMessage(tutoring_session_id=tutoring_session.id, role="assistant", content=answer, hint_level=1)); db.commit(); return {"role": "assistant", "content": answer, "mode": "socratic"}

@app.post("/sessions/{session_id}/finish")
def finish_session(session_id: str, body: SessionFinish, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    if session.status not in ("active", "paused"): raise HTTPException(409, "session is already completed")
    if session.status == "active":
        interval = db.query(StudySessionInterval).filter_by(study_session_id=session.id, ended_at=None).one()
        interval.ended_at=now(); interval.end_reason="completed"; interval.active_seconds=max(0, body.active_seconds-session.active_seconds)
    session.status="completed"; session.ended_at=now(); session.active_seconds=body.active_seconds; session.completion_reason="ward_finished"; session.version += 1
    db.get(Task, session.task_id).status="completed"
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.completed", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id, "active_seconds": session.active_seconds})
    db.commit(); return {"status": "completed"}

@app.post("/wards/{ward_id}/reviews/{review_date}")
def submit_review(ward_id: str, review_date: date, body: SelfReviewCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); row=db.query(SelfReview).filter_by(ward_id=ward_id, review_date=review_date).one_or_none()
    if row is None: row=SelfReview(ward_id=ward_id, review_date=review_date, **body.model_dump()); db.add(row)
    else:
        for k,v in body.model_dump().items(): setattr(row,k,v)
    kit=db.query(FocusKit).filter_by(ward_id=ward_id,review_date=review_date).one_or_none()
    if kit is None: db.add(FocusKit(ward_id=ward_id, review_date=review_date, advice="遇到卡住时，先停两分钟写下已知条件，再继续下一步。"))
    db.flush()
    publish_learning_fact(db, ward_id=ward_id, event_type="self_review.submitted", source_type="self_review", source_id=row.id, payload={"review_date": review_date.isoformat(), "feeling": row.feeling})
    db.commit(); return {"status":"submitted"}

@app.get("/wards/{ward_id}/reviews/{review_date}/insight")
def ward_insight(ward_id: str, review_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); review=db.query(SelfReview).filter_by(ward_id=ward_id,review_date=review_date).one_or_none()
    if review is None: return {"status":"locked"}
    report=db.query(Report).filter_by(ward_id=ward_id,report_date=review_date).one_or_none(); kit=db.query(FocusKit).filter_by(ward_id=ward_id,review_date=review_date).one()
    return {"status":"ready","subjective_timeline":review.timeline_json,"objective_timeline": report.timeline_json if report else [],"advice":kit.advice}

@app.get("/wards/{ward_id}/guardian-story/{story_date}")
def guardian_story(ward_id: str, story_date: date, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    review=db.query(SelfReview).filter_by(ward_id=ward_id,review_date=story_date).one_or_none()
    if review is None: return {"status":"locked"}
    report=db.query(Report).filter_by(ward_id=ward_id,report_date=story_date).one_or_none()
    sessions=db.query(StudySession).filter_by(ward_id=ward_id).all()
    stuck=db.query(TutoringMessage).join(TutoringSession).filter(
        TutoringSession.ward_id == ward_id,
        TutoringMessage.is_stuck_point.is_(True),
    ).count()
    return {"status":"ready","total_seconds":sum(s.active_seconds for s in sessions),"behavior":report.label_breakdown if report else {},"stuck_points":stuck,"communication_suggestions":["可以先肯定孩子今天愿意自己完成计划。", "试着问：哪一步最让你费劲？我想听你讲讲。"]}


@app.post("/auth/register", response_model=TokenPair, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    email = body.email.lower().strip()
    if db.query(Guardian).filter(func.lower(Guardian.email) == email).count():
        raise HTTPException(409, "email already registered")
    user = User(type="guardian")
    db.add(user)
    db.flush()
    guardian = Guardian(id=user.id, name=body.name, email=email, password_hash=hash_secret(body.password), role="admin")
    db.add(guardian)
    db.commit()
    return _tokens(db, guardian)


@app.post("/auth/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    guardian = db.query(Guardian).filter(func.lower(Guardian.email) == body.email.lower().strip()).one_or_none()
    if guardian is None or not verify_secret(body.password, guardian.password_hash):
        raise HTTPException(401, "invalid email or password")
    return _tokens(db, guardian)


@app.post("/auth/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash(body.refresh_token)).one_or_none()
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
    if row is None or row.revoked or expires < now():
        raise HTTPException(401, "invalid or expired refresh token")
    guardian = db.get(Guardian, row.guardian_id)
    row.revoked = True
    db.commit()
    return _tokens(db, guardian)


@app.get("/wards", response_model=list[WardOut])
def list_wards(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    return db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(
        GuardianWard.guardian_id == principal.user_id,
    ).order_by(Ward.display_name).all()


@app.post("/wards", response_model=WardOut, status_code=201)
def create_ward(body: WardCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    user = User(type="ward")
    db.add(user)
    db.flush()
    ward = Ward(id=user.id, **body.model_dump())
    db.add(ward)
    # PostgreSQL validates this FK immediately; persist user_wards before
    # adding guardian_ward_relations rather than relying on ORM insert order.
    db.flush()
    db.add(GuardianWard(guardian_id=principal.user_id, ward_id=user.id))
    db.commit()
    db.refresh(ward)
    return ward


@app.patch("/wards/{ward_id}", response_model=WardOut)
def patch_ward(ward_id: str, body: WardPatch, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    ward = owned_ward(db, principal.user_id, ward_id)
    changes = body.model_dump(exclude_unset=True)
    profile_id = changes.get("analysis_profile_id")
    if profile_id and db.query(AnalysisProfile).filter(
        AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id,
    ).count() == 0:
        raise HTTPException(404, "analysis profile not found")
    for key, value in changes.items():
        setattr(ward, key, value)
    if "analysis_profile_id" in changes:
        db.query(Report).filter(Report.ward_id == ward_id).update(
            {Report.profile_changed: True}, synchronize_session=False,
        )
    db.commit()
    db.refresh(ward)
    return ward


@app.delete("/wards/{ward_id}/data", status_code=204)
def delete_ward_data(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    # Stop derived/runtime state first.  The database deliberately uses NO
    # ACTION FKs, so erasure is explicit and cannot accidentally leave a
    # replayable summary or trace behind.
    thread_ids = [row[0] for row in db.query(ConversationThread.id).filter_by(ward_id=ward_id).all()]
    run_ids = [row[0] for row in db.query(AgentRun.id).filter(AgentRun.ward_id == ward_id).all()]
    if run_ids:
        db.query(AgentStreamEvent).filter(AgentStreamEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(AgentCheckpoint).filter(AgentCheckpoint.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(AgentTrace).filter(AgentTrace.run_id.in_(run_ids)).delete(synchronize_session=False)
    if thread_ids:
        db.query(AgentTrace).filter(AgentTrace.thread_id.in_(thread_ids)).delete(synchronize_session=False)
        db.query(CompanionCommand).filter(CompanionCommand.thread_id.in_(thread_ids)).delete(synchronize_session=False)
    db.query(AgentRun).filter(AgentRun.ward_id == ward_id).delete(synchronize_session=False)
    db.query(CompanionCommand).filter(CompanionCommand.ward_id == ward_id).delete(synchronize_session=False)
    db.query(ConversationThread).filter(ConversationThread.ward_id == ward_id).delete(synchronize_session=False)

    memory_ids = [row[0] for row in db.query(EpisodicMemory.id).filter_by(ward_id=ward_id).all()]
    signal_ids = [row[0] for row in db.query(DerivedSignal.id).filter_by(ward_id=ward_id).all()]
    if memory_ids:
        db.query(EpisodicMemoryEvent).filter(EpisodicMemoryEvent.episodic_memory_id.in_(memory_ids)).delete(synchronize_session=False)
    if signal_ids:
        db.query(DerivedSignalEvent).filter(DerivedSignalEvent.derived_signal_id.in_(signal_ids)).delete(synchronize_session=False)
    db.query(EpisodicMemory).filter(EpisodicMemory.ward_id == ward_id).delete(synchronize_session=False)
    db.query(DerivedSignal).filter(DerivedSignal.ward_id == ward_id).delete(synchronize_session=False)
    db.query(LongTermProfile).filter(LongTermProfile.ward_id == ward_id).delete(synchronize_session=False)
    db.query(LearningEvent).filter(LearningEvent.ward_id == ward_id).delete(synchronize_session=False)
    # Outbox has no Ward FK by design.  Its self-contained envelope is the
    # authoritative routing field for erasure before a worker can replay it.
    for event in db.query(OutboxEvent).filter(OutboxEvent.event_type == "LearningFactRecorded.v1").all():
        if (event.payload or {}).get("ward_id") == ward_id:
            db.delete(event)

    frames = db.query(Frame).filter(Frame.ward_id == ward_id).all()
    for frame in frames:
        storage.delete(frame.oss_key)
    frame_ids = [frame.id for frame in frames]
    if frame_ids:
        db.query(FramePrediction).filter(FramePrediction.frame_id.in_(frame_ids)).delete(synchronize_session=False)
    db.query(BehaviorSegment).filter(BehaviorSegment.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Report).filter(Report.ward_id == ward_id).delete(synchronize_session=False)
    tutor_ids = [row[0] for row in db.query(TutoringSession.id).filter_by(ward_id=ward_id).all()]
    if tutor_ids:
        db.query(TutoringMessage).filter(TutoringMessage.tutoring_session_id.in_(tutor_ids)).delete(synchronize_session=False)
    db.query(TutoringSession).filter(TutoringSession.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Frame).filter(Frame.ward_id == ward_id).delete(synchronize_session=False)
    session_ids = [row[0] for row in db.query(StudySession.id).filter_by(ward_id=ward_id).all()]
    if session_ids:
        db.query(StudySessionInterval).filter(StudySessionInterval.study_session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(StudySession).filter(StudySession.ward_id == ward_id).delete(synchronize_session=False)
    db.query(FocusKit).filter(FocusKit.ward_id == ward_id).delete(synchronize_session=False)
    db.query(SelfReview).filter(SelfReview.ward_id == ward_id).delete(synchronize_session=False)
    db.query(PlanDraft).filter(PlanDraft.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Task).filter(Task.ward_id == ward_id).delete(synchronize_session=False)
    db.query(DailySchedule).filter(DailySchedule.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardInvite).filter(WardInvite.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardCredential).filter(WardCredential.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Device).filter(Device.ward_id == ward_id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)


@app.post("/wards/{ward_id}/devices/invite", status_code=201)
def invite_device(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    code = make_invite_code(db)
    device = Device(
        ward_id=ward_id, invite_code=code,
        invite_code_expires_at=now() + timedelta(minutes=10),
        capture_interval_seconds=settings.capture_interval_seconds,
    )
    db.add(device)
    db.commit()
    return {"device_id": device.id, "invite_code": code, "qr_payload": f"duxue://bind?code={code}", "expires_at": device.invite_code_expires_at}


@app.get("/wards/{ward_id}/devices")
def list_devices(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    cutoff = now() - timedelta(seconds=settings.heartbeat_timeout_seconds)
    devices = db.query(Device).filter(Device.ward_id == ward_id).all()
    result = []
    for device in devices:
        seen = device.last_heartbeat_at
        if seen and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        status = "online" if seen and seen >= cutoff else "offline"
        if device.status != status:
            device.status = status
        result.append({
            "id": device.id, "ward_id": device.ward_id, "device_type": device.device_type,
            "status": status, "last_seen_at": device.last_heartbeat_at,
            "capture_interval_seconds": device.capture_interval_seconds,
        })
    db.commit()
    return result


@app.delete("/devices/{device_id}", status_code=204)
def unbind_device(device_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    device = db.query(Device).join(Ward, Ward.id == Device.ward_id).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(Device.id == device_id, GuardianWard.guardian_id == principal.user_id).one_or_none()
    if device is None:
        raise HTTPException(404, "device not found")
    device.device_token_hash = None
    device.status = "offline"
    db.commit()
    return Response(status_code=204)


@app.post("/devices/bind")
def bind_device(body: DeviceBind, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.invite_code == body.invite_code.upper()).one_or_none()
    expiry = device.invite_code_expires_at if device else None
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if device is None or device.invite_failures >= 5 or expiry < now():
        if device:
            device.invite_failures += 1
            if device.invite_failures >= 5:
                device.invite_code = None
            db.commit()
        raise HTTPException(400, "invite code is invalid or expired")
    raw = random_token()
    device.device_token_hash = token_hash(raw)
    device.invite_code = None
    device.status = "online"
    device.last_heartbeat_at = now()
    device.bound_server_time = now()
    device.bound_elapsed_realtime = body.elapsed_realtime
    ward = db.get(Ward, device.ward_id)
    db.commit()
    return {"device_token": raw, "device_id": device.id, "ward_name": ward.display_name, "capture_interval_seconds": device.capture_interval_seconds}


@app.post("/devices/heartbeat")
def heartbeat(device: Device = Depends(current_device), db: Session = Depends(get_db)):
    device.last_heartbeat_at = now()
    device.status = "online"
    db.commit()
    return {"status": "online", "capture_interval_seconds": device.capture_interval_seconds, "server_time": now()}


@app.post("/frames/upload-url")
def upload_url(body: UploadUrlRequest, request: Request, device: Device = Depends(current_device)):
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    key = f"{device.ward_id}/{date.today().isoformat()}/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@app.put("/uploads/{key:path}", status_code=204)
async def local_upload(key: str, expires: int, signature: str, request: Request):
    if not isinstance(storage, LocalStorage):
        raise HTTPException(404, "local upload endpoint disabled")
    storage.verify(key, expires, signature)
    data = await request.body()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "image must be between 1 byte and 10 MB")
    path = storage.path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return Response(status_code=204)


@app.post("/frames", status_code=201)
def ingest_frame(body: FrameCreate, device: Device = Depends(current_device), db: Session = Depends(get_db)):
    expected_prefix = f"{device.ward_id}/"
    if not body.oss_key.startswith(expected_prefix) or not storage.exists(body.oss_key):
        raise HTTPException(400, "uploaded object not found or does not belong to device")
    existing = db.query(Frame).filter(Frame.oss_key == body.oss_key).one_or_none()
    if existing:
        record_frame(result="duplicate")
        return {"id": existing.id, "captured_at": existing.captured_at, "duplicate": True}
    captured = corrected_time(body.captured_at, body.elapsed_realtime, device.bound_server_time, device.bound_elapsed_realtime)
    if body.study_session_id:
        session = db.get(StudySession, body.study_session_id)
        if session is None or session.ward_id != device.ward_id:
            raise HTTPException(404, "study session not found for device ward")
    frame = Frame(
        device_id=device.id, ward_id=device.ward_id,
        captured_at=captured, oss_key=body.oss_key,
        study_session_id=body.study_session_id,
        purge_after=now() + timedelta(days=settings.frame_retention_days),
    )
    db.add(frame)
    db.flush()
    publish_learning_fact(db, ward_id=device.ward_id, event_type="camera_frame.captured", source_type="frame", source_id=frame.id, occurred_at=captured, source="cam", scope={"study_session_id": body.study_session_id} if body.study_session_id else {}, payload={"device_id": device.id})
    db.commit()
    db.refresh(frame)
    record_frame(result="accepted")
    return {"id": frame.id, "captured_at": frame.captured_at, "duplicate": False}


@app.get("/analysis-profiles")
def profiles(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    rows = db.query(AnalysisProfile).filter(AnalysisProfile.created_by == principal.user_id).all()
    return [{"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt} for row in rows]


@app.get("/analysis-profiles/{profile_id}")
def get_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    labels = db.query(BehaviorLabelConfig).filter(BehaviorLabelConfig.profile_id == profile_id).order_by(BehaviorLabelConfig.priority.desc()).all()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt, "labels": [{"id": label.id, "label_name": label.label_name, "field_prototypes": label.field_prototypes, "priority": label.priority, "is_active": label.is_active} for label in labels]}


@app.post("/analysis-profiles", status_code=201)
def create_profile(body: ProfileCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = AnalysisProfile(created_by=principal.user_id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@app.patch("/analysis-profiles/{profile_id}")
def patch_profile(profile_id: str, body: ProfilePatch, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.commit()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@app.delete("/analysis-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    if db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(GuardianWard.guardian_id == principal.user_id, Ward.analysis_profile_id == profile_id).count():
        raise HTTPException(409, "profile is assigned to a ward")
    db.delete(row); db.commit()
    return Response(status_code=204)


@app.post("/analysis-profiles/{profile_id}/labels", status_code=201)
def add_label(profile_id: str, body: LabelCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    profile = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if profile is None: raise HTTPException(404, "analysis profile not found")
    label = BehaviorLabelConfig(profile_id=profile_id, **body.model_dump())
    db.add(label); db.commit(); db.refresh(label)
    return {"id": label.id, **body.model_dump()}


@app.patch("/analysis-profiles/{profile_id}/labels/{label_id}")
def patch_label(profile_id: str, label_id: str, body: LabelCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    label = db.query(BehaviorLabelConfig).join(AnalysisProfile).filter(BehaviorLabelConfig.id == label_id, BehaviorLabelConfig.profile_id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if label is None: raise HTTPException(404, "behavior label not found")
    for key, value in body.model_dump().items(): setattr(label, key, value)
    db.commit()
    # Classification-only changes can be recomputed from stored fields; mark reports stale meanwhile.
    ward_ids = [row[0] for row in db.query(Ward.id).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(GuardianWard.guardian_id == principal.user_id, Ward.analysis_profile_id == profile_id).all()]
    if ward_ids:
        db.query(Report).filter(Report.ward_id.in_(ward_ids)).update({Report.profile_changed: True}, synchronize_session=False); db.commit()
    return {"id": label.id, **body.model_dump()}


@app.delete("/analysis-profiles/{profile_id}/labels/{label_id}", status_code=204)
def delete_label(profile_id: str, label_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    label = db.query(BehaviorLabelConfig).join(AnalysisProfile).filter(BehaviorLabelConfig.id == label_id, BehaviorLabelConfig.profile_id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if label is None: raise HTTPException(404, "behavior label not found")
    db.delete(label); db.commit(); return Response(status_code=204)


@app.get("/frames")
def list_frames(ward_id: str, report_date: date = Query(alias="date"), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id); start, end = utc_bounds(report_date)
    rows = db.query(Frame, FramePrediction).outerjoin(FramePrediction, FramePrediction.frame_id == Frame.id).filter(Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).order_by(Frame.captured_at).offset(offset).limit(limit).all()
    return [{"id": frame.id, "captured_at": frame.captured_at, "analyzed": frame.analyzed, "structured_fields": frame.structured_fields, "prediction": None if prediction is None else {"label": prediction.behavior_label, "confidence": prediction.confidence, "source": prediction.source, "model_version": prediction.model_version}} for frame, prediction in rows]


@app.post("/analysis/run")
def run_analysis(body: AnalyzeDayRequest, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, body.ward_id)
    return _report(analyze_and_generate(db, ward_id=body.ward_id, report_date=body.report_date, supplied_results=body.results))


@app.get("/reports/daily")
def daily_report(ward_id: str, report_date: date = Query(alias="date"), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    row = db.query(Report).filter(Report.ward_id == ward_id, Report.report_date == report_date).one_or_none()
    if row is None:
        start, end = utc_bounds(report_date)
        has_frames = db.query(Frame).filter(Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).count()
        return {"ward_id": ward_id, "report_date": report_date, "status": "processing" if has_frames else "empty", "total_seconds": 0, "label_breakdown": {}, "timeline_json": [], "profile_changed": False}
    return _report(row)


@app.get("/reports/weekly-trend")
def weekly_trend(ward_id: str, end_date: date | None = None, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=6)
    rows = db.query(Report).filter(Report.ward_id == ward_id, Report.report_date >= start_date, Report.report_date <= end_date).all()
    by_date = {row.report_date: row for row in rows}
    return {"ward_id": ward_id, "days": [{
        "date": day, "total_seconds": by_date[day].total_seconds if day in by_date else 0,
        "learning_seconds": by_date[day].label_breakdown.get("学习", 0) if day in by_date else 0,
    } for day in (start_date + timedelta(days=i) for i in range(7))]}


@app.get("/admin/summary")
def admin_summary(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    if principal.role != "admin":
        raise HTTPException(403, "admin role required")
    return {
        "wards": db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(GuardianWard.guardian_id == principal.user_id).count(),
        "devices": db.query(Device).join(GuardianWard, GuardianWard.ward_id == Device.ward_id).filter(GuardianWard.guardian_id == principal.user_id).count(),
        "online_devices": db.query(Device).join(GuardianWard, GuardianWard.ward_id == Device.ward_id).filter(GuardianWard.guardian_id == principal.user_id, Device.status == "online").count(),
        "frames_pending": db.query(Frame).join(GuardianWard, GuardianWard.ward_id == Frame.ward_id).filter(GuardianWard.guardian_id == principal.user_id, Frame.analyzed.is_(False)).count(),
        "reports": db.query(Report).join(GuardianWard, GuardianWard.ward_id == Report.ward_id).filter(GuardianWard.guardian_id == principal.user_id).count(),
    }
