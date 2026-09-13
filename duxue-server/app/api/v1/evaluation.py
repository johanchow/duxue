from .common import *
from .common import _report, _ward_owned

router = APIRouter(tags=["evaluation"])

@router.post("/wards/{ward_id}/reviews/{review_date}")
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

@router.get("/wards/{ward_id}/reviews/{review_date}/insight")
def ward_insight(ward_id: str, review_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); review=db.query(SelfReview).filter_by(ward_id=ward_id,review_date=review_date).one_or_none()
    if review is None: return {"status":"locked"}
    report=db.query(Report).filter_by(ward_id=ward_id,report_date=review_date).one_or_none(); kit=db.query(FocusKit).filter_by(ward_id=ward_id,review_date=review_date).one()
    return {"status":"ready","subjective_timeline":review.timeline_json,"objective_timeline": report.timeline_json if report else [],"advice":kit.advice}

@router.get("/wards/{ward_id}/guardian-story/{story_date}")
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


@router.get("/reports/daily")
def daily_report(ward_id: str, report_date: date = Query(alias="date"), principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id)
    row = db.query(Report).filter(Report.ward_id == ward_id, Report.report_date == report_date).one_or_none()
    if row is None:
        start, end = utc_bounds(report_date)
        has_frames = db.query(Frame).filter(Frame.ward_id == ward_id, Frame.captured_at >= start, Frame.captured_at < end).count()
        return {"ward_id": ward_id, "report_date": report_date, "status": "processing" if has_frames else "empty", "total_seconds": 0, "label_breakdown": {}, "timeline_json": [], "profile_changed": False}
    return _report(row)


@router.get("/reports/weekly-trend")
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

