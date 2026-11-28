from .common import *
from .common import _report

router = APIRouter(tags=["evaluation"])

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

