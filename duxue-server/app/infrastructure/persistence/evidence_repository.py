"""Capture-owned accepted evidence journal. Call inside the frame transaction."""
from sqlalchemy import select, update

from app.infrastructure.persistence.models import AcceptedEvidence, EvidenceSequence


def record_accepted_evidence(db, frame, assignment_revision):
    existing = db.query(AcceptedEvidence).filter_by(frame_id=frame.id).one_or_none()
    if existing:
        return existing.sequence
    # A transactional UPDATE serializes allocation and commit, unlike nextval().
    dialect = db.bind.dialect.name
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError('unsupported evidence journal database')
    db.execute(insert(EvidenceSequence).values(id=1, value=0).on_conflict_do_nothing())
    sequence = db.execute(update(EvidenceSequence).where(EvidenceSequence.id == 1)
                          .values(value=EvidenceSequence.value+1).returning(EvidenceSequence.value)).scalar_one()
    db.add(AcceptedEvidence(sequence=sequence, frame_id=frame.id, ward_id=frame.ward_id,
                           camera_id=frame.device_id, assignment_revision=assignment_revision,
                           captured_at=frame.captured_at))
    db.flush()
    return sequence


class AcceptedEvidenceQuery:
    def __init__(self, db):
        self.db = db

    def list_accepted(self, *, system_scope: bool, after: int, upper: int | None = None, limit=100):
        if not system_scope:
            raise PermissionError('system evidence scope required')
        if not 1 <= limit <= 500 or after < 0:
            raise ValueError('invalid evidence page')
        if upper is None:
            upper = self.db.execute(select(EvidenceSequence.value).where(EvidenceSequence.id == 1)).scalar_one_or_none() or 0
        rows = self.db.query(AcceptedEvidence).filter(AcceptedEvidence.sequence > after,
                    AcceptedEvidence.sequence <= upper).order_by(AcceptedEvidence.sequence).limit(limit).all()
        return rows, (rows[-1].sequence if rows else upper), upper
