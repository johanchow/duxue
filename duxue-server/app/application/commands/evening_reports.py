"""Zero-input, evidence-versioned evening delivery with deterministic wording."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.application.commands.behavior_observation import digest, lock, utc
from app.application.queries.tutoring_evidence import evening_evidence
from app.application.workflows.observation_workflow import observation_step

from app.infrastructure.persistence.models import (
    GuardianReportInbox,
    GuardianWard,
    ObservationDayRecord,
    ObservationRevisionRecord,
    ObservationSettings,
    ReflectionReportRecord,
    ReflectionReportVersion,
)


class EveningReportCommands:
    def __init__(self, db, clock=lambda: datetime.now(timezone.utc)):
        self.db, self.clock = db, clock

    @observation_step("behavior.report")
    def publish(self, ward_id, day):
        db = self.db
        lock(db, f"observation-ward:{ward_id}")
        setting = db.get(ObservationSettings, ward_id)
        if not setting or not setting.report_enabled:
            return None
        hour, minute = map(int, setting.deadline.split(":"))
        cutoff = datetime.combine(day, time(hour, minute), ZoneInfo(setting.timezone))
        if self.clock() < cutoff:
            return None
        observation = (
            db.query(ObservationDayRecord)
            .filter_by(ward_id=ward_id, local_date=day)
            .one_or_none()
        )
        revision = (
            db.get(ObservationRevisionRecord, (observation.id, observation.revision))
            if observation
            else None
        )
        missing = []
        if not revision:
            missing.append("observation_unavailable")
        snapshot = revision.snapshot if revision else {}
        if snapshot.get("coverage", {}).get("ratio") is None:
            missing.append("coverage_unavailable")
        elif snapshot["coverage"].get("missing_seconds", 0) or snapshot["coverage"].get(
            "unknown_seconds", 0
        ):
            missing.append("observation_incomplete")
        # Existing teaching evidence is a process record, not a verified solution.
        # Keep its provenance and do not invent a pass result.
        try:
            with db.begin_nested():
                teaching = evening_evidence(db, ward_id, day)
        except Exception:
            teaching = {
                "asked_count": None,
                "verified_count": None,
                "certificates": [],
                "missing_reason": "tutoring_source_unavailable",
                "source_refs": [],
            }
        if teaching["missing_reason"]:
            missing.append(teaching["missing_reason"])
        source_vector = {
            "observation": observation.revision if observation else 0,
            "tutoring": digest(teaching),
        }
        projection = None
        if revision:
            projection = {
                "totals": snapshot["totals"],
                "coverage": snapshot["coverage"],
                "episodes": [
                    {
                        key: value
                        for key, value in episode.items()
                        if key != "source_refs"
                    }
                    for episode in snapshot.get("episodes", [])
                ],
                "generated_at": utc(revision.created_at).isoformat(),
            }
        content = {
            "status": "partial" if missing else "ready",
            "timezone": setting.timezone,
            "cutoff_at": cutoff.isoformat(),
            "observation": projection,
            "tutoring": {
                key: value for key, value in teaching.items() if key != "source_refs"
            },
            "missing_reasons": missing,
            "summary": "以下为已收到证据的观察结果；缺失或看不清的时段不作行为判断。"
            if revision
            else "本晚观察证据不足，暂时无法还原学习活动。",
        }
        fingerprint = digest({"content": content, "sources": source_vector})
        report = (
            db.query(ReflectionReportRecord)
            .filter_by(ward_id=ward_id, report_date=day)
            .one_or_none()
        )
        if report and report.fingerprint == fingerprint:
            return report
        if report is None:
            report = ReflectionReportRecord(
                ward_id=ward_id,
                report_date=day,
                timezone=setting.timezone,
                current_version=0,
            )
            db.add(report)
            db.flush()
        report.current_version += 1
        report.fingerprint = fingerprint
        db.add(
            ReflectionReportVersion(
                report_id=report.id,
                version=report.current_version,
                content=content,
                source_vector=source_vector,
                published_at=self.clock(),
            )
        )
        for (guardian_id,) in db.query(GuardianWard.guardian_id).filter_by(
            ward_id=ward_id
        ):
            inbox = db.get(GuardianReportInbox, (guardian_id, report.id))
            if inbox:
                inbox.version = report.current_version
            else:
                db.add(
                    GuardianReportInbox(
                        guardian_id=guardian_id,
                        report_id=report.id,
                        version=report.current_version,
                    )
                )
        return report

    def deadlines(self):
        from app.application.commands.behavior_observation import enqueue

        settings = (
            self.db.query(ObservationSettings).filter_by(report_enabled=True).all()
        )
        count = 0
        for setting in settings:
            lock(self.db, f"observation-ward:{setting.ward_id}")
            today = self.clock().astimezone(ZoneInfo(setting.timezone)).date()
            day = setting.report_next_date or today
            # Persist each deadline before advancing the cursor. Bounded catch-up
            # handles long outages without dropping dates or flooding the queue.
            for _ in range(7):
                if day > today + timedelta(days=1):
                    break
                hour, minute = map(int, setting.deadline.split(":"))
                cutoff = datetime.combine(
                    day, time(hour, minute), ZoneInfo(setting.timezone)
                )
                enqueue(
                    self.db,
                    key=f"report:{setting.ward_id}:{day}:{setting.generation}:{setting.deadline}",
                    ward_id=setting.ward_id,
                    kind="report",
                    payload={"date": day.isoformat(), "generation": setting.generation},
                    at=cutoff,
                )
                count += 1
                day += timedelta(days=1)
            setting.report_next_date = day
            self.db.commit()
        return count
