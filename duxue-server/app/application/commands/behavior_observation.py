"""Transactional observation commands; inference runs outside DB transactions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.contexts.behavior_analysis.domain.observation import (
    Cell,
    EvidenceFrame,
    Manifest,
    ObservationAssembler,
    validate_outcome,
)
from app.infrastructure.persistence.evidence_repository import AcceptedEvidenceQuery
from app.application.workflows.observation_workflow import observation_step

from app.infrastructure.persistence.models import (
    AcceptedEvidence,
    Frame,
    ObservationCursor,
    ObservationDayRecord,
    ObservationInterpretation,
    ObservationJob,
    ObservationRevisionRecord,
    ObservationSettings,
    ObservationWindowRecord,
    OutboxEvent,
)


def utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def wire(value):
    return json.loads(json.dumps(value, default=lambda x: x.isoformat()))


def digest(value):
    return hashlib.sha256(json.dumps(wire(value), sort_keys=True).encode()).hexdigest()


def lock(db, key):
    if db.bind.dialect.name == "postgresql":
        number = int.from_bytes(
            hashlib.sha256(key.encode()).digest()[:8], "big", signed=True
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


def enqueue(db, *, key, ward_id, kind, payload, at):
    existing = db.query(ObservationJob).filter_by(key=key).one_or_none()
    if existing:
        return existing
    job = ObservationJob(
        key=key, ward_id=ward_id, kind=kind, payload=wire(payload), available_at=at
    )
    db.add(job)
    db.flush()
    return job


class ObservationCommands:
    def __init__(self, db, visible_activity, clock=lambda: datetime.now(timezone.utc)):
        self.db, self.visible_activity, self.clock = db, visible_activity, clock

    def scan(self, limit=100):
        db = self.db
        lock(db, "observation-receipt-scan")
        cursor = db.get(ObservationCursor, "accepted")
        if cursor is None:
            cursor = ObservationCursor(name="accepted", value=0)
            db.add(cursor)
        rows, next_cursor, _ = AcceptedEvidenceQuery(db).list_accepted(
            system_scope=True, after=cursor.value, limit=limit
        )
        for row in rows:
            from app.infrastructure.observability.observation import record_lag

            record_lag(
                "capture_to_scan", (self.clock() - utc(row.captured_at)).total_seconds()
            )
            setting = db.get(ObservationSettings, row.ward_id)
            if not setting or not setting.enabled or row.assignment_revision is None:
                continue
            if setting.camera_id != row.camera_id:
                continue
            start = utc(row.captured_at).replace(second=0, microsecond=0)
            # Durable discovery survives moving the receipt watermark before the
            # window closes; no model job exists until open_window executes.
            enqueue(
                db,
                key=f"open:{row.sequence}",
                ward_id=row.ward_id,
                kind="open",
                payload={
                    "camera_id": row.camera_id,
                    "revision": row.assignment_revision,
                    "start": start,
                    "generation": setting.generation,
                },
                at=max(self.clock(), start + timedelta(minutes=1)),
            )
        cursor.value = next_cursor
        db.commit()
        return len(rows)

    def open_window(self, job):
        db = self.db
        lock(db, f"observation-ward:{job.ward_id}")
        db.expire_all()
        setting = db.get(ObservationSettings, job.ward_id)
        if (
            not setting
            or not setting.enabled
            or setting.generation != job.payload["generation"]
        ):
            return
        start = datetime.fromisoformat(job.payload["start"])
        end = start + timedelta(minutes=1)
        if self.clock() < end:
            raise ValueError("window_not_closed")
        camera = job.payload["camera_id"]
        revision = job.payload["revision"]
        lock(db, f"window:{job.ward_id}:{camera}:{revision}:{start.isoformat()}")
        rows = (
            db.query(AcceptedEvidence, Frame)
            .join(Frame, Frame.id == AcceptedEvidence.frame_id)
            .filter(
                AcceptedEvidence.ward_id == job.ward_id,
                AcceptedEvidence.camera_id == camera,
                AcceptedEvidence.assignment_revision == revision,
                AcceptedEvidence.captured_at >= start,
                AcceptedEvidence.captured_at < end,
            )
            .order_by(AcceptedEvidence.captured_at, AcceptedEvidence.sequence)
            .all()
        )
        # Keep one deterministic sample per slot, never overload model budgets
        # when a camera retries or uses a shorter capture interval.
        selected = {}
        for evidence, frame in rows:
            slot = int((utc(evidence.captured_at) - start).total_seconds() // 15)
            if frame.oss_key and utc(frame.purge_after) > self.clock():
                selected.setdefault(slot, (evidence, frame))
        rows = list(selected.values())
        manifest = {
            "ward_id": job.ward_id,
            "camera_id": camera,
            "assignment_revision": revision,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "frames": [
                {
                    "id": e.frame_id,
                    "at": utc(e.captured_at).isoformat(),
                    "sha256": f.sha256,
                }
                for e, f in rows
                if f.oss_key and utc(f.purge_after) > self.clock()
            ],
        }
        fingerprint = digest(
            {
                "manifest": manifest,
                "policy": setting.policy_version,
                "generation": setting.generation,
            }
        )
        window = (
            db.query(ObservationWindowRecord)
            .filter_by(
                ward_id=job.ward_id,
                camera_id=camera,
                assignment_revision=revision,
                start_at=start,
            )
            .one_or_none()
        )
        if window and window.fingerprint == fingerprint:
            return
        if window is None:
            window = ObservationWindowRecord(
                ward_id=job.ward_id,
                camera_id=camera,
                assignment_revision=revision,
                start_at=start,
                end_at=end,
                input_version=1,
                generation=setting.generation,
                fingerprint=fingerprint,
                manifest=manifest,
            )
            db.add(window)
        else:
            window.input_version += 1
            window.fingerprint, window.manifest = fingerprint, manifest
            window.status, window.attempt_token = "pending", None
            window.generation = setting.generation
        db.flush()
        enqueue(
            db,
            key=f"analyze:{window.id}:{window.input_version}",
            ward_id=job.ward_id,
            kind="analyze",
            payload={"window_id": window.id, "input_version": window.input_version},
            at=self.clock(),
        )

    def analyze(self, job):
        db = self.db
        lock(db, f"observation-ward:{job.ward_id}")
        window = db.get(ObservationWindowRecord, job.payload["window_id"])
        setting = db.get(ObservationSettings, job.ward_id)
        if (
            not window
            or not setting
            or not setting.enabled
            or setting.generation != window.generation
            or window.input_version != job.payload["input_version"]
        ):
            return
        if window.status == "interpreted":
            return
        token = str(uuid4())
        window.status, window.attempt_token = "running", token
        payload, fingerprint, generation = (
            window.manifest,
            window.fingerprint,
            window.generation,
        )
        job_id, job_token = job.id, job.token
        window_id, input_version = window.id, window.input_version
        db.commit()
        # Adapter resolves authorized references and returns structured cells plus
        # server-owned model/config provenance. No open DB transaction during AI.
        response = self.visible_activity(payload)
        manifest = Manifest(
            payload["ward_id"],
            payload["camera_id"],
            payload["assignment_revision"],
            datetime.fromisoformat(payload["start"]),
            datetime.fromisoformat(payload["end"]),
            tuple(
                EvidenceFrame(f["id"], datetime.fromisoformat(f["at"]))
                for f in payload["frames"]
            ),
        )
        cells = validate_outcome(manifest, response["cells"])
        lock(db, f"observation-ward:{job.ward_id}")
        db.expire_all()
        active_job = db.get(ObservationJob, job_id)
        if (
            not active_job
            or active_job.token != job_token
            or utc(active_job.lease_until) <= self.clock()
        ):
            return
        window = db.get(ObservationWindowRecord, window_id)
        setting = db.get(ObservationSettings, job.ward_id)
        if (
            not window
            or not setting
            or not setting.enabled
            or setting.generation != generation
            or window.attempt_token != token
            or window.fingerprint != fingerprint
            or window.input_version != input_version
        ):
            return
        db.add(
            ObservationInterpretation(
                window_id=window_id,
                input_version=input_version,
                cells=wire([asdict(c) for c in cells]),
                provenance=response["provenance"],
            )
        )
        window.status, window.attempt_token = "interpreted", None
        day = (
            utc(window.start_at)
            .astimezone(ZoneInfo(setting.timezone))
            .date()
            .isoformat()
        )
        enqueue(
            db,
            key=f"publish:{window_id}:{input_version}",
            ward_id=job.ward_id,
            kind="publish",
            payload={"date": day, "generation": generation},
            at=self.clock(),
        )

    @observation_step("behavior.aggregate")
    def publish_day(self, job):
        from datetime import date, time

        db = self.db
        lock(db, f"observation-ward:{job.ward_id}")
        setting = db.get(ObservationSettings, job.ward_id)
        if (
            not setting
            or not setting.enabled
            or setting.generation != job.payload["generation"]
        ):
            return
        local_date = date.fromisoformat(job.payload["date"])
        start = datetime.combine(
            local_date, time.min, ZoneInfo(setting.timezone)
        ).astimezone(timezone.utc)
        end = datetime.combine(
            local_date + timedelta(days=1), time.min, ZoneInfo(setting.timezone)
        ).astimezone(timezone.utc)
        rows = (
            db.query(ObservationWindowRecord, ObservationInterpretation)
            .outerjoin(
                ObservationInterpretation,
                (ObservationInterpretation.window_id == ObservationWindowRecord.id)
                & (
                    ObservationInterpretation.input_version
                    == ObservationWindowRecord.input_version
                ),
            )
            .filter(
                ObservationWindowRecord.ward_id == job.ward_id,
                ObservationWindowRecord.camera_id == setting.camera_id,
                ObservationWindowRecord.generation == setting.generation,
                ObservationWindowRecord.start_at >= start,
                ObservationWindowRecord.start_at < end,
            )
            .order_by(ObservationWindowRecord.start_at)
            .all()
        )
        cells, sources = [], []
        for window, interpretation in rows:
            sources.append({"window_id": window.id, "version": window.input_version})
            if interpretation is None:
                for frame in window.manifest["frames"]:
                    captured = datetime.fromisoformat(frame["at"])
                    slot = utc(window.start_at) + timedelta(
                        seconds=int(
                            (captured - utc(window.start_at)).total_seconds() // 15
                        )
                        * 15
                    )
                    cells.append(
                        Cell(
                            slot,
                            slot + timedelta(seconds=15),
                            "unknown",
                            (frame["id"],),
                            "analysis_unavailable",
                        )
                    )
                continue
            for c in interpretation.cells:
                cells.append(
                    Cell(
                        datetime.fromisoformat(c["start"]),
                        datetime.fromisoformat(c["end"]),
                        c["activity"],
                        tuple(c["evidence"]),
                        c.get("uncertainty_reason"),
                    )
                )
        # An assignment change can produce two windows in the same minute.
        # Conflicting slots stay unknown; never count both source versions.
        unique_cells = {}
        for cell in cells:
            if cell.start in unique_cells:
                previous = unique_cells[cell.start]
                unique_cells[cell.start] = Cell(
                    cell.start,
                    cell.end,
                    "unknown",
                    tuple(sorted(set(previous.evidence) | set(cell.evidence))),
                    "source_assignment_changed",
                )
            else:
                unique_cells[cell.start] = cell
        cells = list(unique_cells.values())
        ranges = None
        if setting.observation_ranges is not None:
            ranges = [
                (
                    max(start, datetime.fromisoformat(a)),
                    min(end, self.clock(), datetime.fromisoformat(b)),
                )
                for a, b in setting.observation_ranges
                if max(start, datetime.fromisoformat(a))
                < min(end, self.clock(), datetime.fromisoformat(b))
            ]
        snapshot = ObservationAssembler().assemble(cells, ranges)
        snapshot.update(
            sources=sources, policy_version=setting.policy_version, candidates=[]
        )
        fingerprint = digest(snapshot)
        day = (
            db.query(ObservationDayRecord)
            .filter_by(ward_id=job.ward_id, local_date=local_date)
            .one_or_none()
        )
        if day and day.fingerprint == fingerprint:
            return
        if day is None:
            day = ObservationDayRecord(
                ward_id=job.ward_id,
                local_date=local_date,
                timezone=setting.timezone,
                revision=0,
            )
            db.add(day)
            db.flush()
        day.revision += 1
        day.fingerprint = fingerprint
        db.add(
            ObservationRevisionRecord(
                day_id=day.id, revision=day.revision, snapshot=wire(snapshot)
            )
        )
        db.add(
            OutboxEvent(
                aggregate_type="observation_day",
                aggregate_id=day.id,
                event_type="ObservationRevisionPublished.v1",
                payload={
                    "schema_version": "ObservationRevisionPublished.v1",
                    "ward_id": job.ward_id,
                    "day_id": day.id,
                    "revision": day.revision,
                },
            )
        )
        enqueue(
            db,
            key=f"assess:{day.id}:{day.revision}",
            ward_id=job.ward_id,
            kind="assess",
            payload={
                "day_id": day.id,
                "revision": day.revision,
                "generation": setting.generation,
            },
            at=self.clock(),
        )

    def run_next(self):
        """Claim one durable job. Recovery reclaims expired leases in this query."""
        from sqlalchemy import and_, or_

        db = self.db
        current = self.clock()
        started = time.monotonic()
        from app.infrastructure.observability.observation import record_job, record_lag

        job = (
            db.query(ObservationJob)
            .filter(
                or_(
                    and_(
                        ObservationJob.status == "pending",
                        ObservationJob.available_at <= current,
                    ),
                    and_(
                        ObservationJob.status == "running",
                        ObservationJob.lease_until <= current,
                    ),
                )
            )
            .order_by(ObservationJob.available_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            db.rollback()
            return False
        record_lag("queue", (current - utc(job.available_at)).total_seconds())
        job_kind = job.kind
        job.status, job.token = "running", str(uuid4())
        job.attempts += 1
        job.lease_until = current + timedelta(seconds=120)
        job_id, job_token = job.id, job.token
        db.commit()
        try:
            # Lock/recheck the claimed attempt before any short transactional work.
            # Inference deliberately commits this lock and rechecks its token later.
            db.expire_all()
            job = (
                db.query(ObservationJob)
                .filter_by(id=job_id)
                .with_for_update()
                .one_or_none()
            )
            if (
                not job
                or job.token != job_token
                or utc(job.lease_until) <= self.clock()
            ):
                db.rollback()
                return True
            {
                "open": self.open_window,
                "analyze": self.analyze,
                "publish": self.publish_day,
                "assess": self.assess_support,
                "report": self.publish_report,
            }[job.kind](job)
            job = db.get(ObservationJob, job_id)
            if job and job.token == job_token and utc(job.lease_until) > self.clock():
                job.status, job.token, job.lease_until = "done", None, None
                record_job(job_kind, "done", time.monotonic() - started)
            db.commit()
        except Exception:
            record_job(job_kind, "failed", time.monotonic() - started)
            db.rollback()
            job = (
                db.query(ObservationJob)
                .filter_by(id=job_id)
                .with_for_update()
                .one_or_none()
            )
            if job and job.token == job_token:
                job.status = "failed" if job.attempts >= 8 else "pending"
                job.available_at = self.clock() + timedelta(
                    seconds=[1, 5, 30, 120, 600][min(job.attempts - 1, 4)]
                )
                if job.kind == "analyze":
                    lock(db, f"observation-ward:{job.ward_id}")
                    window = db.get(ObservationWindowRecord, job.payload["window_id"])
                    setting = db.get(ObservationSettings, job.ward_id)
                    if (
                        window
                        and setting
                        and setting.enabled
                        and window.generation == setting.generation
                    ):
                        local_day = (
                            utc(window.start_at)
                            .astimezone(ZoneInfo(setting.timezone))
                            .date()
                            .isoformat()
                        )
                        enqueue(
                            db,
                            key=f"publish-unavailable:{window.id}:{window.input_version}:{job.attempts}",
                            ward_id=job.ward_id,
                            kind="publish",
                            payload={
                                "date": local_day,
                                "generation": setting.generation,
                            },
                            at=self.clock(),
                        )
                job.error_code = "observation_job_failed"
                job.token, job.lease_until = None, None
                db.commit()
        return True

    def assess_support(self, job):
        from app.contexts.behavior_analysis.domain.support import (
            eligible_runs,
            validate_assessment,
        )
        from app.infrastructure.persistence.models import SupportAssessment

        db = self.db
        setting = db.get(ObservationSettings, job.ward_id)
        day = db.get(ObservationDayRecord, job.payload["day_id"])
        if (
            not setting
            or not setting.enabled
            or setting.generation != job.payload["generation"]
            or not day
            or day.revision != job.payload["revision"]
        ):
            return
        revision = db.get(ObservationRevisionRecord, (day.id, day.revision))
        snapshot = json.loads(json.dumps(revision.snapshot))
        runs = snapshot["runs"]
        if not runs:
            return
        last = runs[-1]
        start, end = (
            datetime.fromisoformat(last["start"]),
            datetime.fromisoformat(last["end"]),
        )
        evidence = (
            db.query(AcceptedEvidence)
            .filter(
                AcceptedEvidence.frame_id.in_(last["evidence"]),
                AcceptedEvidence.ward_id == job.ward_id,
                AcceptedEvidence.camera_id == setting.camera_id,
            )
            .order_by(AcceptedEvidence.captured_at)
            .all()
        )
        if not evidence:
            return
        observed_at = utc(evidence[-1].captured_at)
        run = {**last, "start": start, "end": end, "observed_at": observed_at}
        from app.application.workflows.observation_workflow import check_eligibility
        if not check_eligibility(bool(eligible_runs([run], self.clock()))):
            return
        frames = evidence[-16:]
        assignments = {e.assignment_revision for e in frames}
        if len(assignments) != 1 or None in assignments:
            return
        has_learning = any(
            r["activity"] in {"writing", "reading_material", "handling_material"}
            for r in runs
        )
        payload = {
            "ward_id": job.ward_id,
            "camera_id": setting.camera_id,
            "assignment_revision": assignments.pop(),
            "trigger": "stillness_reached_duration"
            if last["activity"] == "still_with_material"
            else "other_activity_reached_duration",
            "observed_period": {"start": start.isoformat(), "end": end.isoformat()},
            "learning_context": {"observed_learning": has_learning},
            "frames": [
                {"id": e.frame_id, "at": utc(e.captured_at).isoformat()} for e in frames
            ],
        }
        fingerprint = digest(
            {
                "input": payload,
                "sources": snapshot["sources"],
                "policy": setting.policy_version,
            }
        )
        cached = db.get(SupportAssessment, fingerprint)
        cached_result = cached.result if cached else None
        job_id, job_token = job.id, job.token
        day_id, source_revision, generation = day.id, day.revision, setting.generation
        db.commit()
        if cached_result is None:
            try:
                result = self.visible_activity.assess(payload)
            except Exception:
                result = {
                    "decision": "uncertain",
                    "evidence_refs": [],
                    "observed_basis": "",
                    "uncertainty_reason": "assessment_unavailable",
                    "provenance": {},
                }
        else:
            result = cached_result
        model_data = {
            key: value for key, value in result.items() if key != "provenance"
        }
        candidate = validate_assessment(
            model_data,
            [f["id"] for f in payload["frames"]],
            has_learning_context=has_learning,
        )
        lock(db, f"observation-ward:{job.ward_id}")
        db.expire_all()
        day = db.get(ObservationDayRecord, day_id)
        setting = db.get(ObservationSettings, job.ward_id)
        active_job = db.get(ObservationJob, job_id)
        if (
            not day
            or not setting
            or not setting.enabled
            or setting.generation != generation
            or day.revision != source_revision
            or not active_job
            or active_job.token != job_token
            or utc(active_job.lease_until) <= self.clock()
        ):
            return
        if db.get(SupportAssessment, fingerprint) is None:
            db.add(
                SupportAssessment(
                    fingerprint=fingerprint, ward_id=job.ward_id, result=result
                )
            )
        if not candidate or self.clock() - observed_at > timedelta(seconds=60):
            return
        snapshot["candidates"] = [
            {
                **candidate.model_dump(),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "observed_at": observed_at.isoformat(),
                "fresh_until": (observed_at + timedelta(seconds=120)).isoformat(),
                "assessment_version": fingerprint,
                "source_revision": source_revision,
            }
        ]
        day.revision += 1
        day.fingerprint = digest(snapshot)
        db.add(
            ObservationRevisionRecord(
                day_id=day.id, revision=day.revision, snapshot=snapshot
            )
        )
        db.add(
            OutboxEvent(
                aggregate_type="observation_day",
                aggregate_id=day.id,
                event_type="ObservationRevisionPublished.v1",
                payload={
                    "schema_version": "ObservationRevisionPublished.v1",
                    "ward_id": job.ward_id,
                    "day_id": day.id,
                    "revision": day.revision,
                },
            )
        )

    def publish_report(self, job):
        from datetime import date

        from app.application.commands.evening_reports import EveningReportCommands

        setting = self.db.get(ObservationSettings, job.ward_id)
        if (
            setting
            and setting.report_enabled
            and setting.generation == job.payload["generation"]
        ):
            EveningReportCommands(self.db, self.clock).publish(
                job.ward_id, date.fromisoformat(job.payload["date"])
            )
