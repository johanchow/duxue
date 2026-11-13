from datetime import timedelta
from uuid import uuid4

from app.infrastructure.persistence.evidence_repository import (
    AcceptedEvidenceQuery,
    record_accepted_evidence,
)
from app.infrastructure.persistence.models import (
    AcceptedEvidence,
    Device,
    Frame,
    User,
    Ward,
    now,
)


def make_frame(db, captured=None):
    uid = str(uuid4())
    db.add(User(id=uid, type='ward'))
    db.flush()
    db.add(Ward(id=uid, display_name='test'))
    db.flush()
    device = Device(ward_id=uid)
    db.add(device)
    db.flush()
    frame = Frame(ward_id=uid, device_id=device.id, captured_at=captured or now(), purge_after=now()+timedelta(days=1))
    db.add(frame)
    db.flush()
    return frame


def test_late_capture_gets_new_receipt_and_stable_snapshot(db):
    first = make_frame(db)
    assert record_accepted_evidence(db, first, 7) == 1
    db.commit()
    rows, cursor, upper = AcceptedEvidenceQuery(db).list_accepted(system_scope=True, after=0)
    late = make_frame(db, now()-timedelta(days=1))
    assert record_accepted_evidence(db, late, 2) == 2
    db.commit()
    assert AcceptedEvidenceQuery(db).list_accepted(system_scope=True, after=cursor, upper=upper)[0] == []
    rows, cursor, upper = AcceptedEvidenceQuery(db).list_accepted(system_scope=True, after=cursor)
    assert rows[0].frame_id == late.id
    assert rows[0].assignment_revision == 2


def test_rollback_cannot_publish_watermark(db):
    frame = make_frame(db)
    record_accepted_evidence(db, frame, 1)
    db.rollback()
    assert AcceptedEvidenceQuery(db).list_accepted(system_scope=True, after=0) == ([], 0, 0)


def test_receipt_idempotent_and_assignment_immutable(db):
    frame = make_frame(db)
    record_accepted_evidence(db, frame, 3)
    db.commit()
    assert record_accepted_evidence(db, frame, 9) == 1
    assert db.query(AcceptedEvidence).one().assignment_revision == 3
