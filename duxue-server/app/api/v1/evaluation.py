from .common import *
from .common import _report, _ward_owned
from app.api.schemas import SelfReviewConfirmRequest, SelfReviewDraftRequest
from app.application.commands.self_reviews import confirm_self_review
from app.application.queries.review_draft import propose_review_aspects
from app.application.queries.review_prompt import review_invitation
from app.application.queries.self_reviews import get_recent_self_reviews
from app.infrastructure.persistence.models import SelfReviewAspect, SelfReviewVersion

router = APIRouter(tags=["evaluation"])

@router.post("/wards/{ward_id}/reviews/{review_date}")
def submit_review(ward_id: str, review_date: date, body: SelfReviewCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    row = confirm_self_review(
        db, ward_id=ward_id, review_date=review_date,
        raw_expression=body.reflection or body.feeling, aspects=[],
        expected_version=None, feeling=body.feeling,
    )
    row.timeline_json = body.timeline_json
    db.commit()
    return {"status": "submitted", "review_id": row.id, "version": row.version}


@router.post("/wards/{ward_id}/reviews/{review_date}/draft")
def draft_review(ward_id: str, review_date: date, body: SelfReviewDraftRequest,
                 principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    current = db.query(SelfReview).filter_by(ward_id=ward_id, review_date=review_date).one_or_none()
    return {
        "raw_expression": body.raw_expression.strip(),
        "aspects": propose_review_aspects(body.raw_expression),
        "expected_version": current.version if current else 0,
    }


@router.get("/wards/{ward_id}/reviews/{review_date}/prompt")
def review_prompt(ward_id: str, review_date: date,
                  principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    return review_invitation(db, ward_id=ward_id, review_date=review_date)


@router.put("/wards/{ward_id}/reviews/{review_date}/confirm")
def confirm_review(ward_id: str, review_date: date, body: SelfReviewConfirmRequest,
                   principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    row = confirm_self_review(
        db, ward_id=ward_id, review_date=review_date,
        raw_expression=body.raw_expression,
        aspects=[aspect.model_dump() for aspect in body.aspects],
        expected_version=body.expected_version,
        source_message_id=body.source_message_id,
    )
    db.commit()
    return {"status": "confirmed", "review_id": row.id, "version": row.version}


@router.get("/wards/{ward_id}/reviews/recent")
def recent_reviews(ward_id: str, end_date: date | None = None, days: int = 5,
                   task_ref: str | None = None, topic_ref: str | None = None,
                   limit: int = 8, char_budget: int = 2000,
                   principal: Principal = Depends(current_ward),
                   db: Session = Depends(get_db)):
    return {"items": get_recent_self_reviews(
        db, actor_id=principal.user_id, actor_role=principal.role,
        ward_id=ward_id, use_case="ward_history", end_date=end_date or date.today(),
        days=days, task_ref=task_ref, topic_ref=topic_ref,
        item_budget=limit, char_budget=char_budget,
    )}


@router.get("/wards/{ward_id}/reviews/{review_date}")
def get_review(ward_id: str, review_date: date,
               principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    review = db.query(SelfReview).filter_by(ward_id=ward_id, review_date=review_date).one_or_none()
    if review is None:
        raise HTTPException(404, "summary not found")
    version = db.query(SelfReviewVersion).filter_by(review_id=review.id, version=review.version).one_or_none()
    aspects = db.query(SelfReviewAspect).filter_by(review_id=review.id, review_version=review.version).all()
    return {
        "review_id": review.id, "review_date": review_date,
        "version": review.version,
        "raw_expression": version.raw_expression if version else review.reflection or review.feeling,
        "aspects": [{"aspect_id": a.id, "dimension": a.dimension, "statement": a.statement,
                     "source_quote": a.source_quote, "task_ref": a.task_ref, "topic_ref": a.topic_ref}
                    for a in aspects],
        "status": "confirmed" if version else "legacy_unstructured",
    }

@router.get("/wards/{ward_id}/reviews/{review_date}/insight")
def ward_insight(ward_id: str, review_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); review=db.query(SelfReview).filter_by(ward_id=ward_id,review_date=review_date).one_or_none()
    if review is None: return {"status":"locked"}
    report=db.query(Report).filter_by(ward_id=ward_id,report_date=review_date).one_or_none()
    return {"status":"ready","subjective_timeline":review.timeline_json,"objective_timeline": report.timeline_json if report else []}

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

