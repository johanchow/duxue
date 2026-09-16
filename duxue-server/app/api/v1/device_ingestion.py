from .common import *

router = APIRouter(tags=["device-ingestion"])

@router.post("/wards/{ward_id}/devices/invite", status_code=201)
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


@router.get("/wards/{ward_id}/devices")
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


@router.delete("/devices/{device_id}", status_code=204)
def unbind_device(device_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    device = db.query(Device).join(Ward, Ward.id == Device.ward_id).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(Device.id == device_id, GuardianWard.guardian_id == principal.user_id).one_or_none()
    if device is None:
        raise HTTPException(404, "device not found")
    device.device_token_hash = None
    device.status = "offline"
    db.commit()
    return Response(status_code=204)


@router.post("/devices/bind")
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


@router.post("/devices/heartbeat")
def heartbeat(device: Device = Depends(current_device), db: Session = Depends(get_db)):
    device.last_heartbeat_at = now()
    device.status = "online"
    db.commit()
    return {"status": "online", "capture_interval_seconds": device.capture_interval_seconds, "server_time": now()}


@router.post("/frames/upload-url")
def upload_url(body: UploadUrlRequest, request: Request, device: Device = Depends(current_device)):
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    key = f"{device.ward_id}/{date.today().isoformat()}/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@router.put("/uploads/{key:path}", status_code=204)
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


@router.post("/frames", status_code=201)
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


