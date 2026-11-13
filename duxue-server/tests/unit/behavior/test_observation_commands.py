from datetime import timedelta

from app.application.commands.behavior_observation import ObservationCommands
from app.infrastructure.persistence.evidence_repository import record_accepted_evidence
from app.infrastructure.persistence.models import (
    ObservationInterpretation,
    ObservationJob,
    ObservationRevisionRecord,
    ObservationSettings,
    ObservationWindowRecord,
    OutboxEvent,
)
from tests.unit.behavior.test_evidence_journal import make_frame
from tests.unit.behavior.test_observation import T


def setup(db):
    frame = make_frame(db, T)
    frame.oss_key = f"{frame.ward_id}/fixture.jpg"
    record_accepted_evidence(db, frame, 1)
    setting = ObservationSettings(
        ward_id=frame.ward_id,
        enabled=True,
        camera_id=frame.device_id,
        observation_ranges=[[T.isoformat(), (T + timedelta(minutes=1)).isoformat()]],
    )
    db.add(setting)
    db.commit()
    return frame, setting


def model(payload):
    return {
        "cells": [
            {
                "start": payload["start"],
                "end": (T + timedelta(seconds=15)).isoformat(),
                "activity": "writing",
                "evidence_frame_ids": [payload["frames"][0]["id"]],
            }
        ],
        "provenance": {"model": "fixed-fixture", "prompt_version": "test"},
    }


def test_receipt_to_published_revision_idempotent(db):
    frame, _ = setup(db)
    commands = ObservationCommands(db, model, lambda: T + timedelta(minutes=1))
    assert commands.scan() == 1
    for _ in range(4):
        assert commands.run_next()
    snapshot = db.query(ObservationRevisionRecord).one().snapshot
    assert snapshot["totals"] == {"writing": 15.0, "missing": 45.0}
    assert db.query(ObservationInterpretation).count() == 1
    assert (
        db.query(OutboxEvent)
        .filter_by(event_type="ObservationRevisionPublished.v1")
        .count()
        == 1
    )
    assert commands.scan() == 0
    assert commands.run_next() is False


def test_no_model_call_before_window_end(db):
    setup(db)
    commands = ObservationCommands(
        db, lambda _: (_ for _ in ()).throw(AssertionError()), lambda: T
    )
    commands.scan()
    assert commands.run_next() is False
    assert db.query(ObservationWindowRecord).count() == 0


def test_model_failure_preserves_retry_without_observation(db):
    setup(db)

    def fail(_):
        raise TimeoutError()

    commands = ObservationCommands(db, fail, lambda: T + timedelta(minutes=1))
    commands.scan()
    commands.run_next()
    commands.run_next()
    assert db.query(ObservationInterpretation).count() == 0
    assert db.query(ObservationJob).filter_by(kind="analyze").one().status == "pending"


def test_disabled_during_inference_cannot_publish(db):
    frame, setting = setup(db)

    def disable(payload):
        setting.enabled = False
        setting.generation += 1
        db.commit()
        return model(payload)

    commands = ObservationCommands(db, disable, lambda: T + timedelta(minutes=1))
    commands.scan()
    commands.run_next()
    commands.run_next()
    assert db.query(ObservationInterpretation).count() == 0


def test_published_observation_is_projected_into_report(db):
    from app.application.commands.evening_reports import EveningReportCommands
    from app.infrastructure.persistence.models import ReflectionReportVersion

    frame, setting = setup(db)
    setting.report_enabled = True
    db.commit()
    commands = ObservationCommands(db, model, lambda: T + timedelta(minutes=1))
    commands.scan()
    while commands.run_next():
        pass
    report = EveningReportCommands(db, lambda: T + timedelta(days=1)).publish(
        frame.ward_id, T.date()
    )
    db.commit()
    content = db.get(ReflectionReportVersion, (report.id, 1)).content
    assert content["observation"]["totals"]["writing"] == 15
    assert content["status"] == "partial"
    assert "runs" not in content["observation"]


def test_expired_model_attempt_cannot_publish(db):
    setup(db)
    clock = [T + timedelta(minutes=1)]

    def slow(payload):
        clock[0] += timedelta(seconds=121)
        return model(payload)

    commands = ObservationCommands(db, slow, lambda: clock[0])
    commands.scan()
    commands.run_next()
    commands.run_next()
    assert db.query(ObservationInterpretation).count() == 0
    assert db.query(ObservationJob).filter_by(kind="analyze").one().status == "running"


def test_received_frame_with_failed_analysis_is_unknown_not_missing(db):
    setup(db)

    def fail(_):
        raise TimeoutError()

    commands = ObservationCommands(db, fail, lambda: T + timedelta(minutes=1))
    commands.scan()
    for _ in range(3):
        commands.run_next()
    snapshot = db.query(ObservationRevisionRecord).one().snapshot
    assert snapshot["totals"] == {"unknown": 15.0, "missing": 45.0}
    assert snapshot["coverage"]["received_seconds"] == 15
