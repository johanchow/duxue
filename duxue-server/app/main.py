from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .dependencies import Principal, current_device, current_guardian
from .models import (
    AnalysisProfile, BehaviorLabelConfig, BehaviorSegment, Device, Frame, FramePrediction,
    Guardian, GuardianWard, RefreshToken, Report, Tenant, User, Ward, now,
)
from .schemas import (
    AnalyzeDayRequest, DeviceBind, FrameCreate, LabelCreate, LoginRequest, ProfileCreate,
    ProfilePatch, RefreshRequest, RegisterRequest, TokenPair, UploadUrlRequest, WardCreate,
    WardOut, WardPatch,
)
from .security import create_access_token, hash_secret, random_token, token_hash, verify_secret
from .services import analyze_and_generate, corrected_time, make_invite_code, owned_ward, utc_bounds
from .storage import LocalStorage, storage


app = FastAPI(title="读学 Server", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4173", "http://127.0.0.1:4173"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)


def _tokens(db: Session, guardian: Guardian, tenant_id: str) -> TokenPair:
    refresh = random_token()
    db.add(RefreshToken(
        guardian_id=guardian.id, token_hash=token_hash(refresh),
        expires_at=now() + timedelta(days=settings.refresh_token_days),
    ))
    db.commit()
    return TokenPair(
        access_token=create_access_token(user_id=guardian.id, tenant_id=tenant_id, role=guardian.role),
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


@app.post("/auth/register", response_model=TokenPair, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    email = body.email.lower().strip()
    if db.query(Guardian).filter(func.lower(Guardian.email) == email).count():
        raise HTTPException(409, "email already registered")
    tenant = Tenant(name=body.tenant_name or f"{body.name}的家庭")
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, type="guardian")
    db.add(user)
    db.flush()
    guardian = Guardian(id=user.id, name=body.name, email=email, password_hash=hash_secret(body.password), role="owner")
    db.add(guardian)
    db.commit()
    return _tokens(db, guardian, tenant.id)


@app.post("/auth/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    guardian = db.query(Guardian).filter(func.lower(Guardian.email) == body.email.lower().strip()).one_or_none()
    if guardian is None or not verify_secret(body.password, guardian.password_hash):
        raise HTTPException(401, "invalid email or password")
    user = db.get(User, guardian.id)
    return _tokens(db, guardian, user.tenant_id)


@app.post("/auth/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash(body.refresh_token)).one_or_none()
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
    if row is None or row.revoked or expires < now():
        raise HTTPException(401, "invalid or expired refresh token")
    guardian = db.get(Guardian, row.guardian_id)
    user = db.get(User, row.guardian_id)
    row.revoked = True
    db.commit()
    return _tokens(db, guardian, user.tenant_id)


@app.get("/wards", response_model=list[WardOut])
def list_wards(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    return db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(
        Ward.tenant_id == principal.tenant_id, GuardianWard.guardian_id == principal.user_id,
    ).order_by(Ward.display_name).all()


@app.post("/wards", response_model=WardOut, status_code=201)
def create_ward(body: WardCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    user = User(tenant_id=principal.tenant_id, type="ward")
    db.add(user)
    db.flush()
    ward = Ward(id=user.id, tenant_id=principal.tenant_id, **body.model_dump())
    db.add(ward)
    db.add(GuardianWard(tenant_id=principal.tenant_id, guardian_id=principal.user_id, ward_id=user.id))
    db.commit()
    db.refresh(ward)
    return ward


@app.patch("/wards/{ward_id}", response_model=WardOut)
def patch_ward(ward_id: str, body: WardPatch, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    ward = owned_ward(db, principal.tenant_id, ward_id)
    changes = body.model_dump(exclude_unset=True)
    profile_id = changes.get("analysis_profile_id")
    if profile_id and db.query(AnalysisProfile).filter(
        AnalysisProfile.id == profile_id, AnalysisProfile.tenant_id == principal.tenant_id,
    ).count() == 0:
        raise HTTPException(404, "analysis profile not found")
    for key, value in changes.items():
        setattr(ward, key, value)
    if "analysis_profile_id" in changes:
        db.query(Report).filter(Report.tenant_id == principal.tenant_id, Report.ward_id == ward_id).update(
            {Report.profile_changed: True}, synchronize_session=False,
        )
    db.commit()
    db.refresh(ward)
    return ward


@app.delete("/wards/{ward_id}/data", status_code=204)
def delete_ward_data(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id)
    frames = db.query(Frame).filter(Frame.tenant_id == principal.tenant_id, Frame.ward_id == ward_id).all()
    for frame in frames:
        storage.delete(frame.oss_key)
    frame_ids = [frame.id for frame in frames]
    if frame_ids:
        db.query(FramePrediction).filter(FramePrediction.tenant_id == principal.tenant_id, FramePrediction.frame_id.in_(frame_ids)).delete(synchronize_session=False)
    db.query(BehaviorSegment).filter(BehaviorSegment.tenant_id == principal.tenant_id, BehaviorSegment.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Report).filter(Report.tenant_id == principal.tenant_id, Report.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Frame).filter(Frame.tenant_id == principal.tenant_id, Frame.ward_id == ward_id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)


@app.post("/wards/{ward_id}/devices/invite", status_code=201)
def invite_device(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id)
    code = make_invite_code(db)
    device = Device(
        tenant_id=principal.tenant_id, ward_id=ward_id, invite_code=code,
        invite_code_expires_at=now() + timedelta(minutes=10),
        capture_interval_seconds=settings.capture_interval_seconds,
    )
    db.add(device)
    db.commit()
    return {"device_id": device.id, "invite_code": code, "qr_payload": f"duxue://bind?code={code}", "expires_at": device.invite_code_expires_at}


@app.get("/wards/{ward_id}/devices")
def list_devices(ward_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id)
    cutoff = now() - timedelta(minutes=3)
    devices = db.query(Device).filter(Device.tenant_id == principal.tenant_id, Device.ward_id == ward_id).all()
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
    device = db.query(Device).filter(Device.id == device_id, Device.tenant_id == principal.tenant_id).one_or_none()
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
    key = f"{device.tenant_id}/{device.ward_id}/{date.today().isoformat()}/{secrets.token_hex(16)}.{extension}"
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
    expected_prefix = f"{device.tenant_id}/{device.ward_id}/"
    if not body.oss_key.startswith(expected_prefix) or not storage.exists(body.oss_key):
        raise HTTPException(400, "uploaded object not found or does not belong to device")
    existing = db.query(Frame).filter(Frame.oss_key == body.oss_key).one_or_none()
    if existing:
        return {"id": existing.id, "captured_at": existing.captured_at, "duplicate": True}
    captured = corrected_time(body.captured_at, body.elapsed_realtime, device.bound_server_time, device.bound_elapsed_realtime)
    frame = Frame(
        tenant_id=device.tenant_id, device_id=device.id, ward_id=device.ward_id,
        captured_at=captured, oss_key=body.oss_key,
        purge_after=now() + timedelta(days=settings.frame_retention_days),
    )
    db.add(frame)
    db.commit()
    db.refresh(frame)
    return {"id": frame.id, "captured_at": frame.captured_at, "duplicate": False}


@app.get("/analysis-profiles")
def profiles(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    rows = db.query(AnalysisProfile).filter(AnalysisProfile.tenant_id == principal.tenant_id).all()
    return [{"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt} for row in rows]


@app.get("/analysis-profiles/{profile_id}")
def get_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.tenant_id == principal.tenant_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    labels = db.query(BehaviorLabelConfig).filter(BehaviorLabelConfig.tenant_id == principal.tenant_id, BehaviorLabelConfig.profile_id == profile_id).order_by(BehaviorLabelConfig.priority.desc()).all()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt, "labels": [{"id": label.id, "label_name": label.label_name, "field_prototypes": label.field_prototypes, "priority": label.priority, "is_active": label.is_active} for label in labels]}


@app.post("/analysis-profiles", status_code=201)
def create_profile(body: ProfileCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = AnalysisProfile(tenant_id=principal.tenant_id, created_by=principal.user_id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@app.patch("/analysis-profiles/{profile_id}")
def patch_profile(profile_id: str, body: ProfilePatch, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.tenant_id == principal.tenant_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.commit()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@app.delete("/analysis-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.tenant_id == principal.tenant_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    if db.query(Ward).filter(Ward.tenant_id == principal.tenant_id, Ward.analysis_profile_id == profile_id).count():
        raise HTTPException(409, "profile is assigned to a ward")
    db.delete(row); db.commit()
    return Response(status_code=204)


@app.post("/analysis-profiles/{profile_id}/labels", status_code=201)
def add_label(profile_id: str, body: LabelCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    profile = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.tenant_id == principal.tenant_id).one_or_none()
    if profile is None: raise HTTPException(404, "analysis profile not found")
    label = BehaviorLabelConfig(tenant_id=principal.tenant_id, profile_id=profile_id, **body.model_dump())
    db.add(label); db.commit(); db.refresh(label)
    return {"id": label.id, **body.model_dump()}


@app.patch("/analysis-profiles/{profile_id}/labels/{label_id}")
def patch_label(profile_id: str, label_id: str, body: LabelCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    label = db.query(BehaviorLabelConfig).filter(BehaviorLabelConfig.id == label_id, BehaviorLabelConfig.profile_id == profile_id, BehaviorLabelConfig.tenant_id == principal.tenant_id).one_or_none()
    if label is None: raise HTTPException(404, "behavior label not found")
    for key, value in body.model_dump().items(): setattr(label, key, value)
    db.commit()
    # Classification-only changes can be recomputed from stored fields; mark reports stale meanwhile.
    ward_ids = [row[0] for row in db.query(Ward.id).filter(Ward.tenant_id == principal.tenant_id, Ward.analysis_profile_id == profile_id).all()]
    if ward_ids:
        db.query(Report).filter(Report.tenant_id == principal.tenant_id, Report.ward_id.in_(ward_ids)).update({Report.profile_changed: True}, synchronize_session=False); db.commit()
    return {"id": label.id, **body.model_dump()}


@app.delete("/analysis-profiles/{profile_id}/labels/{label_id}", status_code=204)
def delete_label(profile_id: str, label_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    label = db.query(BehaviorLabelConfig).filter(BehaviorLabelConfig.id == label_id, BehaviorLabelConfig.profile_id == profile_id, BehaviorLabelConfig.tenant_id == principal.tenant_id).one_or_none()
    if label is None: raise HTTPException(404, "behavior label not found")
    db.delete(label); db.commit(); return Response(status_code=204)


@app.get("/frames")
def list_frames(ward_id: str, report_date: date = Query(alias="date"), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id); start, end = utc_bounds(report_date)
    rows = db.query(Frame, FramePrediction).outerjoin(FramePrediction, FramePrediction.frame_id == Frame.id).filter(Frame.tenant_id == principal.tenant_id, Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).order_by(Frame.captured_at).offset(offset).limit(limit).all()
    return [{"id": frame.id, "captured_at": frame.captured_at, "analyzed": frame.analyzed, "structured_fields": frame.structured_fields, "prediction": None if prediction is None else {"label": prediction.behavior_label, "confidence": prediction.confidence, "source": prediction.source, "model_version": prediction.model_version}} for frame, prediction in rows]


@app.post("/analysis/run")
def run_analysis(body: AnalyzeDayRequest, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    return _report(analyze_and_generate(db, tenant_id=principal.tenant_id, ward_id=body.ward_id, report_date=body.report_date, supplied_results=body.results))


@app.get("/reports/daily")
def daily_report(ward_id: str, report_date: date = Query(alias="date"), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id)
    row = db.query(Report).filter(Report.tenant_id == principal.tenant_id, Report.ward_id == ward_id, Report.report_date == report_date).one_or_none()
    if row is None:
        start, end = utc_bounds(report_date)
        has_frames = db.query(Frame).filter(Frame.tenant_id == principal.tenant_id, Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).count()
        return {"ward_id": ward_id, "report_date": report_date, "status": "processing" if has_frames else "empty", "total_seconds": 0, "label_breakdown": {}, "timeline_json": [], "profile_changed": False}
    return _report(row)


@app.get("/reports/weekly-trend")
def weekly_trend(ward_id: str, end_date: date | None = None, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.tenant_id, ward_id)
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=6)
    rows = db.query(Report).filter(Report.tenant_id == principal.tenant_id, Report.ward_id == ward_id, Report.report_date >= start_date, Report.report_date <= end_date).all()
    by_date = {row.report_date: row for row in rows}
    return {"ward_id": ward_id, "days": [{
        "date": day, "total_seconds": by_date[day].total_seconds if day in by_date else 0,
        "learning_seconds": by_date[day].label_breakdown.get("学习", 0) if day in by_date else 0,
    } for day in (start_date + timedelta(days=i) for i in range(7))]}


@app.get("/admin/summary")
def admin_summary(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    if principal.role not in {"owner", "admin"}:
        raise HTTPException(403, "admin role required")
    return {
        "wards": db.query(Ward).filter(Ward.tenant_id == principal.tenant_id).count(),
        "devices": db.query(Device).filter(Device.tenant_id == principal.tenant_id).count(),
        "online_devices": db.query(Device).filter(Device.tenant_id == principal.tenant_id, Device.status == "online").count(),
        "frames_pending": db.query(Frame).filter(Frame.tenant_id == principal.tenant_id, Frame.analyzed.is_(False)).count(),
        "reports": db.query(Report).filter(Report.tenant_id == principal.tenant_id).count(),
    }
