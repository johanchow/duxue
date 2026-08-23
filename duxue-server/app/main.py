from __future__ import annotations

import asyncio
import json
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .asr import AsrConfigurationError, DashscopeRealtimeAsr, forward_asr_events
from .database import Base, SessionLocal, engine, get_db
from .dependencies import Principal, _bearer, current_device, current_guardian, current_ward, guardian_principal_for_token
from .models import (
    AnalysisProfile, BehaviorLabelConfig, BehaviorSegment, Device, Frame, FramePrediction,
    Guardian, GuardianWard, RefreshToken, Report, User, Ward, WardCredential, WardInvite,
    Assignment, DailyPlan, PlanItem, StudySession, StudyMessage, SelfReview, FocusKit, now,
)
from .schemas import (
    AnalyzeDayRequest, DeviceBind, FrameCreate, LabelCreate, LoginRequest, ProfileCreate,
    ProfilePatch, RefreshRequest, RegisterRequest, TokenPair, UploadUrlRequest, WardCreate,
    WardOut, WardPatch, WardBindRequest, WardLoginRequest, AssignmentCreate, PlanDraft,
    MessageCreate, SessionFinish, SelfReviewCreate,
)
from .security import create_access_token, hash_secret, random_token, token_hash, verify_secret
from .services import analyze_and_generate, corrected_time, make_invite_code, owned_ward, utc_bounds
from .storage import LocalStorage, storage


app = FastAPI(title="读学 Server", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allow_origins),
    allow_methods=["*"], allow_headers=["*"],
)


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
            principal = guardian_principal_for_token(_bearer(websocket.headers.get("authorization")), db)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        start = await websocket.receive_json()
        ward_ids = start.get("ward_ids") if start.get("type") == "start" else None
        if not isinstance(ward_ids, list) or not ward_ids or not all(isinstance(value, str) for value in ward_ids):
            await websocket.send_json({"type": "error", "message": "ward_ids are required"})
            await websocket.close(code=1008)
            return
        for ward_id in ward_ids:
            owned_ward(db, principal.user_id, ward_id)

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
    code = secrets.token_hex(4).upper()
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
        credential = WardCredential(ward_id=invite.ward_id, pin_hash=hash_secret(body.pin)); db.add(credential)
    else: credential.pin_hash = hash_secret(body.pin)
    invite.consumed_at = now(); db.commit()
    return {"ward_id": invite.ward_id, "access_token": create_access_token(user_id=invite.ward_id, role="ward"), "token_type": "bearer"}

@app.post("/ward-auth/login")
def ward_login(body: WardLoginRequest, db: Session = Depends(get_db)):
    credential = db.get(WardCredential, body.ward_id); ward = db.get(Ward, body.ward_id)
    if credential is None or ward is None or not verify_secret(body.pin, credential.pin_hash): raise HTTPException(401, "invalid ward credentials")
    return {"ward_id": ward.id, "access_token": create_access_token(user_id=ward.id, role="ward"), "token_type": "bearer"}

@app.post("/wards/{ward_id}/assignments", status_code=201)
def create_assignment(ward_id: str, body: AssignmentCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id); row = Assignment(ward_id=ward_id, **body.model_dump()); db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "title": row.title, "status": row.status, "source": row.source}

@app.get("/wards/{ward_id}/assignments")
def assignments(ward_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); return [{"id": x.id, "title": x.title, "details": x.details, "due_date": x.due_date, "status": x.status} for x in db.query(Assignment).filter_by(ward_id=ward_id, status="open").all()]

@app.put("/wards/{ward_id}/plans/{plan_date}")
def save_plan(ward_id: str, plan_date: date, body: PlanDraft, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if body.plan_date != plan_date: raise HTTPException(400, "date mismatch")
    plan = db.query(DailyPlan).filter_by(ward_id=ward_id, plan_date=plan_date).one_or_none()
    if plan is None: plan = DailyPlan(ward_id=ward_id, plan_date=plan_date); db.add(plan); db.flush()
    if plan.status == "confirmed": raise HTTPException(409, "confirmed plan cannot be changed")
    db.query(PlanItem).filter_by(plan_id=plan.id).delete()
    for position, item in enumerate(body.items): db.add(PlanItem(plan_id=plan.id, assignment_id=item.get("assignment_id"), title=item.get("title", "学习任务"), position=position, planned_minutes=int(item.get("planned_minutes", 30))))
    db.commit(); return {"id": plan.id, "status": plan.status}

@app.post("/wards/{ward_id}/plans/{plan_date}/confirm")
def confirm_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); plan = db.query(DailyPlan).filter_by(ward_id=ward_id, plan_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    plan.status = "confirmed"; plan.confirmed_at = now(); db.commit(); return {"id": plan.id, "status": plan.status}

@app.get("/wards/{ward_id}/plans/{plan_date}")
def get_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); plan = db.query(DailyPlan).filter_by(ward_id=ward_id, plan_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    return {"id": plan.id, "status": plan.status, "items": [{"id": x.id, "title": x.title, "planned_minutes": x.planned_minutes, "status": x.status} for x in db.query(PlanItem).filter_by(plan_id=plan.id).order_by(PlanItem.position)]}

@app.post("/plan-items/{item_id}/sessions", status_code=201)
def start_session(item_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    item = db.get(PlanItem, item_id); plan = db.get(DailyPlan, item.plan_id) if item else None
    if plan is None or plan.ward_id != principal.user_id: raise HTTPException(404, "plan item not found")
    row = StudySession(ward_id=principal.user_id, plan_item_id=item.id); item.status="active"; db.add(row); db.commit(); return {"id": row.id, "status": row.status}

@app.post("/sessions/{session_id}/messages")
def tutor(session_id: str, body: MessageCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    db.add(StudyMessage(session_id=session_id, role="ward", content=body.content, is_stuck_point=True))
    # Model routing remains injectable; this safe fallback keeps an unavailable provider from blocking study.
    answer = "先别急着找答案。你能说说题目已知什么、要解决什么吗？把第一步写出来，我们一起检查。"
    db.add(StudyMessage(session_id=session_id, role="assistant", content=answer)); db.commit(); return {"role": "assistant", "content": answer, "mode": "socratic"}

@app.post("/sessions/{session_id}/finish")
def finish_session(session_id: str, body: SessionFinish, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    session.status="completed"; session.ended_at=now(); session.active_seconds=body.active_seconds; db.get(PlanItem, session.plan_item_id).status="completed"; db.commit(); return {"status": "completed"}

@app.post("/wards/{ward_id}/reviews/{review_date}")
def submit_review(ward_id: str, review_date: date, body: SelfReviewCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); row=db.query(SelfReview).filter_by(ward_id=ward_id, review_date=review_date).one_or_none()
    if row is None: row=SelfReview(ward_id=ward_id, review_date=review_date, **body.model_dump()); db.add(row)
    else:
        for k,v in body.model_dump().items(): setattr(row,k,v)
    kit=db.query(FocusKit).filter_by(ward_id=ward_id,review_date=review_date).one_or_none()
    if kit is None: db.add(FocusKit(ward_id=ward_id, review_date=review_date, advice="遇到卡住时，先停两分钟写下已知条件，再继续下一步。"))
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
    stuck=sum(db.query(StudyMessage).filter_by(session_id=s.id,is_stuck_point=True).count() for s in sessions)
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
    frames = db.query(Frame).filter(Frame.ward_id == ward_id).all()
    for frame in frames:
        storage.delete(frame.oss_key)
    frame_ids = [frame.id for frame in frames]
    if frame_ids:
        db.query(FramePrediction).filter(FramePrediction.frame_id.in_(frame_ids)).delete(synchronize_session=False)
    db.query(BehaviorSegment).filter(BehaviorSegment.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Report).filter(Report.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Frame).filter(Frame.ward_id == ward_id).delete(synchronize_session=False)
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
        return {"id": existing.id, "captured_at": existing.captured_at, "duplicate": True}
    captured = corrected_time(body.captured_at, body.elapsed_realtime, device.bound_server_time, device.bound_elapsed_realtime)
    frame = Frame(
        device_id=device.id, ward_id=device.ward_id,
        captured_at=captured, oss_key=body.oss_key,
        purge_after=now() + timedelta(days=settings.frame_retention_days),
    )
    db.add(frame)
    db.commit()
    db.refresh(frame)
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
