from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta, timezone

from celery import Celery
from celery.schedules import crontab

from app.ai import DashscopeInference
from app.config import settings
from app.database import SessionLocal
from app.models import AnalysisBatch, AnalysisProfile, Device, Frame, Report, Ward, now
from app.services import analyze_and_generate, utc_bounds


celery_app = Celery("duxue", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "Asia/Shanghai"
celery_app.conf.beat_schedule = {
    "submit-daily-batches": {"task": "duxue.submit_daily_batches", "schedule": crontab(hour=settings.batch_submit_hour, minute=0)},
    "poll-batches": {"task": "duxue.poll_batches", "schedule": crontab(minute="*/10")},
    "offline-devices": {"task": "duxue.mark_offline_devices", "schedule": crontab(minute="*")},
    "purge-expired-frames": {"task": "duxue.purge_expired_frames", "schedule": crontab(hour=3, minute=20)},
}


def _prompt_map(db, ward_ids: set[str]) -> dict[str, str]:
    rows = db.query(Ward, AnalysisProfile).outerjoin(AnalysisProfile, AnalysisProfile.id == Ward.analysis_profile_id).filter(Ward.id.in_(ward_ids)).all()
    return {ward.id: profile.extra_observation_prompt if profile else "" for ward, profile in rows}


@celery_app.task(name="duxue.submit_daily_batches")
def submit_daily_batches(day: str | None = None) -> int:
    target = date.fromisoformat(day) if day else date.today()
    start, end = utc_bounds(target)
    db = SessionLocal()
    try:
        pending = db.query(Frame).filter(Frame.analyzed.is_(False), Frame.batch_id.is_(None), Frame.captured_at >= start, Frame.captured_at < end).order_by(Frame.captured_at).all()
        if not pending:
            return 0
        submitted = 0
        # Batch inference no longer has a tenant partition; a batch may safely contain
        # frames for several wards because each result is routed by its ward_id.
        for frames in (pending,):
            client = DashscopeInference()
            provider_id = client.submit(frames, _prompt_map(db, {frame.ward_id for frame in frames}))
            batch = AnalysisBatch(batch_date=target, provider_batch_id=provider_id, status="submitted", frame_count=len(frames))
            db.add(batch); db.flush()
            for frame in frames: frame.batch_id = batch.id
            for ward_id in {frame.ward_id for frame in frames}:
                report = db.query(Report).filter(Report.ward_id == ward_id, Report.report_date == target).one_or_none()
                if report is None: db.add(Report(ward_id=ward_id, report_date=target, status="processing"))
                else: report.status = "processing"
            db.commit(); submitted += 1
        return submitted
    finally: db.close()


@celery_app.task(name="duxue.poll_batches")
def poll_batches() -> int:
    db = SessionLocal(); completed = 0
    try:
        batches = db.query(AnalysisBatch).filter(AnalysisBatch.status.in_(["submitted", "running"])).all()
        client = DashscopeInference() if batches else None
        for batch in batches:
            status, results = client.retrieve(batch.provider_batch_id)
            frames = db.query(Frame).filter(Frame.batch_id == batch.id).all()
            submitted_at = batch.submitted_at.replace(tzinfo=timezone.utc) if batch.submitted_at.tzinfo is None else batch.submitted_at
            if status != "completed" and now() - submitted_at >= timedelta(hours=settings.batch_fallback_after_hours):
                prompts = _prompt_map(db, {frame.ward_id for frame in frames})
                for frame in frames:
                    if frame.id not in results: results[frame.id] = client.realtime(frame, prompts.get(frame.ward_id, ""))
                status = "completed"; batch.fallback_used = True
            if status == "completed":
                by_ward: dict[str, dict] = defaultdict(dict)
                for frame in frames:
                    if frame.id in results: by_ward[frame.ward_id][frame.id] = results[frame.id]
                for ward_id, ward_results in by_ward.items():
                    analyze_and_generate(db, ward_id=ward_id, report_date=batch.batch_date, supplied_results=ward_results)
                batch.status = "completed"; batch.completed_at = now(); completed += 1
            elif status in {"failed", "expired", "cancelled"}: batch.status = "failed"
            else: batch.status = "running"
            db.commit()
        return completed
    finally: db.close()


@celery_app.task(name="duxue.mark_offline_devices")
def mark_offline_devices() -> int:
    db = SessionLocal()
    try:
        cutoff = now() - timedelta(seconds=settings.heartbeat_timeout_seconds)
        count = db.query(Device).filter(Device.status == "online", Device.last_heartbeat_at < cutoff).update({Device.status: "offline"}, synchronize_session=False)
        db.commit(); return count
    finally: db.close()


@celery_app.task(name="duxue.purge_expired_frames")
def purge_expired_frames() -> int:
    from app.storage import storage
    db = SessionLocal()
    try:
        frames = db.query(Frame).filter(Frame.purge_after < now(), Frame.training_candidate.is_(False)).all()
        for frame in frames:
            storage.delete(frame.oss_key)
            # Keep structured fields for future classifier recomputation; remove only sensitive image reference.
            frame.oss_key = None
        db.commit(); return len(frames)
    finally: db.close()


# `celery -A infrastructure.messaging.celery_tasks worker` expects this name.
app = celery_app
