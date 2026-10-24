from .common import *
from .common import _tokens, _ward_tokens
import hashlib
import hmac
import re

from sqlalchemy import text

from app.infrastructure.messaging.email import send_email_code

router = APIRouter(tags=["identity"])

@router.post("/wards/{ward_id}/login-invite", status_code=201)
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

@router.post("/ward-auth/bind")
def ward_bind(body: WardBindRequest, db: Session = Depends(get_db)):
    invite = db.query(WardInvite).filter(WardInvite.code == body.invite_code.upper(), WardInvite.consumed_at.is_(None)).one_or_none()
    if invite is None or invite.expires_at.replace(tzinfo=timezone.utc) < now():
        raise HTTPException(400, "invite code is invalid or expired")
    credential = db.get(WardCredential, invite.ward_id)
    if credential is None:
        credential = WardCredential(ward_id=invite.ward_id); db.add(credential)
        db.flush()
    else:
        credential.session_version += 1
    db.query(WardRefreshToken).filter(
        WardRefreshToken.ward_id == invite.ward_id,
        WardRefreshToken.revoked.is_(False),
    ).update({WardRefreshToken.revoked: True}, synchronize_session=False)
    invite.consumed_at = now()
    token_pair = _ward_tokens(db, credential)
    return {"ward_id": invite.ward_id, **token_pair.model_dump()}

@router.get("/ward/profile")
def ward_profile(principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    ward = db.get(Ward, principal.user_id)
    guardians = db.query(Guardian).join(GuardianWard, GuardianWard.guardian_id == Guardian.id).filter(GuardianWard.ward_id == principal.user_id).order_by(Guardian.name).all()
    return {"id": ward.id, "display_name": ward.display_name, "guardians": [{"id": guardian.id, "name": guardian.name} for guardian in guardians]}


def _email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 255 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "invalid email")
    return email


def _code_hash(email: str, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"email-code:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _email_lock(db: Session, email: str) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(email.encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _ip_hash(request: Request) -> str:
    # Use the socket peer, never an untrusted X-Forwarded-For header.
    host = request.client.host if request.client else "unknown"
    return hmac.new(settings.secret_key.encode(), host.encode(), hashlib.sha256).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.post("/auth/email-code/send", status_code=202)
def send_code(body: EmailCodeRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    email = _email(body.email)
    current = now()
    ip_hash = _ip_hash(request)
    try:
        _email_lock(db, email)
        db.query(EmailAuthChallenge).filter(EmailAuthChallenge.created_at < current - timedelta(days=1)).delete()
        latest = db.query(EmailAuthChallenge).filter_by(email=email).order_by(EmailAuthChallenge.created_at.desc()).first()
        if latest and _utc(latest.created_at) > current - timedelta(seconds=60):
            raise HTTPException(429, "请稍后再获取验证码")
        email_count = db.query(EmailAuthChallenge).filter(EmailAuthChallenge.email == email, EmailAuthChallenge.created_at >= current - timedelta(hours=1)).count()
        ip_count = db.query(EmailAuthChallenge).filter(EmailAuthChallenge.request_ip_hash == ip_hash, EmailAuthChallenge.created_at >= current - timedelta(hours=1)).count()
        if email_count >= 5 or ip_count >= 20:
            raise HTTPException(429, "验证码请求过于频繁，请稍后再试")
        if latest and latest.consumed_at is None:
            latest.consumed_at = current
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(EmailAuthChallenge(email=email, code_hash=_code_hash(email, code), request_ip_hash=ip_hash, created_at=current, expires_at=current + timedelta(minutes=10), attempts=0))
        db.flush()
        send_email_code(recipient=email, code=code)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(503, "邮件发送失败，请稍后重试") from None
    return {"message": "验证码已发送"}


def _consume_code(db: Session, email: str, code: str, request: Request) -> None:
    _email_lock(db, email)
    current = now()
    ip_hash = _ip_hash(request)
    db.query(EmailAuthFailure).filter(EmailAuthFailure.created_at < current - timedelta(days=1)).delete()
    failed_email = db.query(EmailAuthFailure).filter(EmailAuthFailure.email == email, EmailAuthFailure.created_at >= current - timedelta(hours=1)).count()
    failed_ip = db.query(EmailAuthFailure).filter(EmailAuthFailure.request_ip_hash == ip_hash, EmailAuthFailure.created_at >= current - timedelta(hours=1)).count()
    if failed_email >= 20 or failed_ip >= 100:
        db.rollback()
        raise HTTPException(429, "验证码尝试过于频繁，请稍后重试")
    challenge = db.query(EmailAuthChallenge).filter(EmailAuthChallenge.email == email, EmailAuthChallenge.consumed_at.is_(None)).order_by(EmailAuthChallenge.created_at.desc()).with_for_update().first()
    if challenge is None or _utc(challenge.expires_at) <= current or challenge.attempts >= 5:
        db.add(EmailAuthFailure(email=email, request_ip_hash=ip_hash, created_at=current))
        db.commit()
        raise HTTPException(400, "验证码无效或已过期")
    if not hmac.compare_digest(challenge.code_hash, _code_hash(email, code)):
        challenge.attempts += 1
        db.add(EmailAuthFailure(email=email, request_ip_hash=ip_hash, created_at=current))
        db.commit()
        raise HTTPException(400, "验证码无效或已过期")
    challenge.consumed_at = current


@router.post("/auth/register", response_model=TokenPair, status_code=201)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    email = _email(body.email)
    _consume_code(db, email, body.code, request)
    if db.query(Guardian).filter(func.lower(Guardian.email) == email).count():
        db.rollback()
        raise HTTPException(409, "email already registered")
    user = User(type="guardian")
    db.add(user)
    db.flush()
    guardian = Guardian(id=user.id, name=body.name, email=email, role="admin")
    db.add(guardian)
    db.commit()
    return _tokens(db, guardian)


@router.post("/auth/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    email = _email(body.email)
    _consume_code(db, email, body.code, request)
    guardian = db.query(Guardian).filter(func.lower(Guardian.email) == email).one_or_none()
    if guardian is None:
        db.rollback()
        raise HTTPException(404, "account not found")
    db.commit()
    return _tokens(db, guardian)


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash(body.refresh_token)).one_or_none()
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
    if row is None or row.revoked or expires < now():
        raise HTTPException(401, "invalid or expired refresh token")
    guardian = db.get(Guardian, row.guardian_id)
    row.revoked = True
    db.commit()
    return _tokens(db, guardian)


@router.post("/ward-auth/refresh", response_model=TokenPair)
def refresh_ward(body: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    row = db.query(WardRefreshToken).filter(
        WardRefreshToken.token_hash == token_hash(body.refresh_token),
    ).one_or_none()
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row and row.expires_at.tzinfo is None else (row.expires_at if row else None)
    credential = db.get(WardCredential, row.ward_id) if row else None
    if (
        row is None
        or row.revoked
        or expires < now()
        or credential is None
        or row.session_version != credential.session_version
    ):
        raise HTTPException(401, "invalid or expired refresh token")
    row.revoked = True
    db.commit()
    return _ward_tokens(db, credential)


@router.get("/wards", response_model=list[WardOut])
def list_wards(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    return db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(
        GuardianWard.guardian_id == principal.user_id,
    ).order_by(Ward.display_name).all()


@router.post("/wards", response_model=WardOut, status_code=201)
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


@router.patch("/wards/{ward_id}", response_model=WardOut)
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


@router.delete("/wards/{ward_id}/data", status_code=204)
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
        attachment_rows = db.query(CompanionMessage.attachment_refs).filter(
            CompanionMessage.thread_id.in_(thread_ids)
        ).all()
        for (refs,) in attachment_rows:
            for key in refs or []:
                storage.delete(key)
        db.query(AgentTrace).filter(AgentTrace.thread_id.in_(thread_ids)).delete(synchronize_session=False)
        db.query(CompanionMessage).filter(CompanionMessage.thread_id.in_(thread_ids)).delete(synchronize_session=False)
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
    db.query(PronunciationLesson).filter(PronunciationLesson.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Frame).filter(Frame.ward_id == ward_id).delete(synchronize_session=False)
    session_ids = [row[0] for row in db.query(StudySession.id).filter_by(ward_id=ward_id).all()]
    if session_ids:
        db.query(StudySessionInterval).filter(StudySessionInterval.study_session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(StudySession).filter(StudySession.ward_id == ward_id).delete(synchronize_session=False)
    review_ids = [row[0] for row in db.query(SelfReview.id).filter_by(ward_id=ward_id).all()]
    if review_ids:
        db.query(SelfReviewAspect).filter(SelfReviewAspect.review_id.in_(review_ids)).delete(synchronize_session=False)
        db.query(SelfReviewVersion).filter(SelfReviewVersion.review_id.in_(review_ids)).delete(synchronize_session=False)
    db.query(SelfReview).filter(SelfReview.ward_id == ward_id).delete(synchronize_session=False)
    db.query(PlanDraft).filter(PlanDraft.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Task).filter(Task.ward_id == ward_id).delete(synchronize_session=False)
    db.query(DailySchedule).filter(DailySchedule.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardInvite).filter(WardInvite.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardRefreshToken).filter(WardRefreshToken.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardCredential).filter(WardCredential.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Device).filter(Device.ward_id == ward_id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)
