from .common import *
from .common import _report

router = APIRouter(tags=["behavior-analysis"])

@router.get("/analysis-profiles")
def profiles(principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    rows = db.query(AnalysisProfile).filter(AnalysisProfile.created_by == principal.user_id).all()
    return [{"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt} for row in rows]


@router.get("/analysis-profiles/{profile_id}")
def get_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    labels = db.query(BehaviorLabelConfig).filter(BehaviorLabelConfig.profile_id == profile_id).order_by(BehaviorLabelConfig.priority.desc()).all()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt, "labels": [{"id": label.id, "label_name": label.label_name, "field_prototypes": label.field_prototypes, "priority": label.priority, "is_active": label.is_active} for label in labels]}


@router.post("/analysis-profiles", status_code=201)
def create_profile(body: ProfileCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = AnalysisProfile(created_by=principal.user_id, **body.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@router.patch("/analysis-profiles/{profile_id}")
def patch_profile(profile_id: str, body: ProfilePatch, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    db.commit()
    return {"id": row.id, "name": row.name, "extra_observation_prompt": row.extra_observation_prompt}


@router.delete("/analysis-profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    row = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if row is None: raise HTTPException(404, "analysis profile not found")
    if db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(GuardianWard.guardian_id == principal.user_id, Ward.analysis_profile_id == profile_id).count():
        raise HTTPException(409, "profile is assigned to a ward")
    db.delete(row); db.commit()
    return Response(status_code=204)


@router.post("/analysis-profiles/{profile_id}/labels", status_code=201)
def add_label(profile_id: str, body: LabelCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    profile = db.query(AnalysisProfile).filter(AnalysisProfile.id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if profile is None: raise HTTPException(404, "analysis profile not found")
    label = BehaviorLabelConfig(profile_id=profile_id, **body.model_dump())
    db.add(label); db.commit(); db.refresh(label)
    return {"id": label.id, **body.model_dump()}


@router.patch("/analysis-profiles/{profile_id}/labels/{label_id}")
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


@router.delete("/analysis-profiles/{profile_id}/labels/{label_id}", status_code=204)
def delete_label(profile_id: str, label_id: str, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    label = db.query(BehaviorLabelConfig).join(AnalysisProfile).filter(BehaviorLabelConfig.id == label_id, BehaviorLabelConfig.profile_id == profile_id, AnalysisProfile.created_by == principal.user_id).one_or_none()
    if label is None: raise HTTPException(404, "behavior label not found")
    db.delete(label); db.commit(); return Response(status_code=204)


@router.get("/frames")
def list_frames(ward_id: str, report_date: date = Query(alias="date"), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id); start, end = utc_bounds(report_date)
    rows = db.query(Frame, FramePrediction).outerjoin(FramePrediction, FramePrediction.frame_id == Frame.id).filter(Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).order_by(Frame.captured_at).offset(offset).limit(limit).all()
    return [{"id": frame.id, "captured_at": frame.captured_at, "analyzed": frame.analyzed, "structured_fields": frame.structured_fields, "prediction": None if prediction is None else {"label": prediction.behavior_label, "confidence": prediction.confidence, "source": prediction.source, "model_version": prediction.model_version}} for frame, prediction in rows]


@router.post("/analysis/run")
def run_analysis(body: AnalyzeDayRequest, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, body.ward_id)
    return _report(analyze_and_generate(db, ward_id=body.ward_id, report_date=body.report_date, supplied_results=body.results))


@router.get("/admin/summary")
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
