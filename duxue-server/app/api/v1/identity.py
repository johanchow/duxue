from .common import *
from .common import _tokens, _ward_tokens

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


@router.post("/auth/register", response_model=TokenPair, status_code=201)
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


@router.post("/auth/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    guardian = db.query(Guardian).filter(func.lower(Guardian.email) == body.email.lower().strip()).one_or_none()
    if guardian is None or not verify_secret(body.password, guardian.password_hash):
        raise HTTPException(401, "invalid email or password")
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
    db.query(WardRefreshToken).filter(WardRefreshToken.ward_id == ward_id).delete(synchronize_session=False)
    db.query(WardCredential).filter(WardCredential.ward_id == ward_id).delete(synchronize_session=False)
    db.query(Device).filter(Device.ward_id == ward_id).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)


