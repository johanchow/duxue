from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .domain import Point, RuleClassifier, build_segments, smooth
from .models import BehaviorLabelConfig, BehaviorSegment, Frame, FramePrediction, Report, Ward, now


classifier = RuleClassifier(Path(__file__).parents[1] / "classifier" / "rules.yaml")


def utc_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def owned_ward(db: Session, tenant_id: str, ward_id: str) -> Ward:
    ward = db.query(Ward).filter(Ward.id == ward_id, Ward.tenant_id == tenant_id).one_or_none()
    if ward is None:
        raise HTTPException(404, "ward not found")
    return ward


def make_invite_code(db: Session) -> str:
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    for _ in range(20):
        value = "".join(secrets.choice(alphabet) for _ in range(6))
        from .models import Device
        if db.query(Device).filter(Device.invite_code == value).count() == 0:
            return value
    raise HTTPException(503, "could not allocate invite code")


def classify_for_ward(db: Session, ward: Ward, fields: dict) -> tuple[str, float]:
    """Apply active profile labels first, then the safe system default rules."""
    if ward.analysis_profile_id:
        labels = db.query(BehaviorLabelConfig).filter(
            BehaviorLabelConfig.tenant_id == ward.tenant_id,
            BehaviorLabelConfig.profile_id == ward.analysis_profile_id,
            BehaviorLabelConfig.is_active.is_(True),
        ).order_by(BehaviorLabelConfig.priority.desc()).all()
        best: tuple[int, int, str] | None = None
        for label in labels:
            hits = 0
            total = 0
            for field, prototypes in (label.field_prototypes or {}).items():
                observed = str(fields.get(field, "")).lower()
                for prototype in prototypes:
                    total += 1
                    if str(prototype).lower() in observed:
                        hits += 1
            candidate = (hits, label.priority, label.label_name)
            if hits and (best is None or candidate > best):
                best = candidate
        if best:
            return best[2], min(1.0, 0.6 + best[0] * 0.1)
    return classifier.classify(fields)


def corrected_time(frame_time: datetime, elapsed: int | None, bound_time: datetime | None, bound_elapsed: int | None) -> datetime:
    if elapsed is not None and bound_time is not None and bound_elapsed is not None and elapsed >= bound_elapsed:
        return bound_time + timedelta(milliseconds=elapsed - bound_elapsed)
    if frame_time.tzinfo is None:
        frame_time = frame_time.replace(tzinfo=timezone.utc)
    # Grossly wrong clocks are safer to replace with receive time.
    if abs((frame_time - now()).total_seconds()) > 24 * 3600:
        return now()
    return frame_time


def analyze_and_generate(
    db: Session, *, tenant_id: str, ward_id: str, report_date: date,
    supplied_results: dict[str, dict] | None = None,
) -> Report:
    ward = owned_ward(db, tenant_id, ward_id)
    start, end = utc_bounds(report_date)
    frames = db.query(Frame).filter(
        Frame.tenant_id == tenant_id, Frame.ward_id == ward_id,
        Frame.captured_at >= start, Frame.captured_at < end,
    ).order_by(Frame.captured_at).all()
    if not frames:
        raise HTTPException(404, "no frames for this date")

    supplied_results = supplied_results or {}
    points: list[Point] = []
    for frame in frames:
        fields = supplied_results.get(frame.id) or frame.structured_fields
        if fields is None:
            # Local deterministic inference makes the development stack runnable.
            fields = {"desc_summary": "无法确定当前行为", "seat_status": "在座"}
        label, confidence = classify_for_ward(db, ward, fields)
        frame.structured_fields = fields
        frame.analyzed = True
        prediction = db.query(FramePrediction).filter(FramePrediction.frame_id == frame.id).one_or_none()
        if prediction is None:
            prediction = FramePrediction(tenant_id=tenant_id, frame_id=frame.id)
            db.add(prediction)
        prediction.behavior_label = label
        prediction.confidence = confidence
        prediction.source = "api" if frame.id in supplied_results else "local"
        prediction.model_version = "qwen3-vl-flash" if frame.id in supplied_results else "local-deterministic-v1"
        points.append(Point(frame.id, frame.captured_at, label, confidence))

    segments = build_segments(smooth(points), settings.capture_interval_seconds)
    db.query(BehaviorSegment).filter(
        BehaviorSegment.tenant_id == tenant_id,
        BehaviorSegment.ward_id == ward_id,
        BehaviorSegment.report_date == report_date,
    ).delete(synchronize_session=False)
    breakdown: dict[str, int] = defaultdict(int)
    timeline: list[dict] = []
    for item in segments:
        db.add(BehaviorSegment(
            tenant_id=tenant_id, ward_id=ward_id, report_date=report_date,
            seg_start=item["start"], seg_end=item["end"], behavior_label=item["label"],
            frame_count=item["frame_count"], confidence_avg=item["confidence_avg"],
        ))
        breakdown[item["label"]] += item["duration_seconds"]
        timeline.append({
            "start": item["start"].isoformat(), "end": item["end"].isoformat(),
            "label": item["label"], "frame_count": item["frame_count"],
            "confidence": round(item["confidence_avg"], 3),
        })

    report = db.query(Report).filter(
        Report.tenant_id == tenant_id, Report.ward_id == ward_id, Report.report_date == report_date,
    ).one_or_none()
    if report is None:
        report = Report(tenant_id=tenant_id, ward_id=ward_id, report_date=report_date)
        db.add(report)
    report.total_seconds = sum(breakdown.values())
    report.label_breakdown = dict(breakdown)
    report.timeline_json = timeline
    report.profile_changed = False
    report.status = "ready"
    report.generated_at = now()
    db.commit()
    db.refresh(report)
    return report
