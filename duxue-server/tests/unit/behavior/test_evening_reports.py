from datetime import timedelta

from app.application.commands.evening_reports import EveningReportCommands
from app.infrastructure.persistence.models import (
    ObservationSettings,
    ReflectionReportRecord,
    ReflectionReportVersion,
)
from tests.unit.behavior.test_evidence_journal import make_frame
from tests.unit.behavior.test_observation import T


def test_zero_observation_and_no_self_review_still_publish(db):
    frame = make_frame(db)
    db.add(ObservationSettings(ward_id=frame.ward_id, report_enabled=True))
    db.commit()
    service = EveningReportCommands(db, lambda: T + timedelta(hours=3))
    service.publish(frame.ward_id, T.date())
    db.commit()
    row = db.query(ReflectionReportVersion).one()
    assert row.content["observation"] is None
    assert row.content["status"] == "partial"
    assert row.content["tutoring"]["verified_count"] == 0
    service.publish(frame.ward_id, T.date())
    db.commit()
    assert db.query(ReflectionReportVersion).count() == 1


def test_before_deadline_never_publishes_fake_zero_report(db):
    frame = make_frame(db)
    db.add(ObservationSettings(ward_id=frame.ward_id, report_enabled=True))
    db.commit()
    assert EveningReportCommands(db, lambda: T).publish(frame.ward_id, T.date()) is None
    assert db.query(ReflectionReportRecord).count() == 0


def test_deadlines_are_durable_and_do_not_depend_on_frames(db):
    from app.infrastructure.persistence.models import ObservationJob
    from tests.support.factories import create_ward

    ward = create_ward(db)
    db.add(ObservationSettings(ward_id=ward.id, report_enabled=True))
    db.commit()
    service = EveningReportCommands(db, lambda: T)
    assert service.deadlines() == 2
    assert db.query(ObservationJob).filter_by(kind="report").count() == 2
    assert service.deadlines() == 0
