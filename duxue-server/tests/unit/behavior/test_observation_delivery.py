from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.infrastructure.persistence.models import ObservationConsumerInbox, OutboxEvent
from app.workers.observation_tasks import deliver_observation_events
from tests.unit.behavior.test_evidence_journal import make_frame


def test_bad_event_retries_without_blocking_valid_lifecycle(db, db_engine):
    frame = make_frame(db)
    broken = OutboxEvent(aggregate_type='observation_day', aggregate_id=str(uuid4()),
        event_type='ObservationRevisionPublished.v1', payload={'schema_version': 'wrong'})
    ready = OutboxEvent(aggregate_type='help_offer', aggregate_id=str(uuid4()),
        event_type='HelpOfferReady.v1', payload={'schema_version': 'HelpOfferReady.v1', 'ward_id': frame.ward_id})
    db.add_all([broken, ready]); db.commit()
    with patch('app.workers.observation_tasks.SessionLocal', sessionmaker(bind=db_engine)):
        assert deliver_observation_events() == 1
        assert deliver_observation_events() == 0
    db.expire_all()
    assert db.get(OutboxEvent, broken.id).attempts == 1
    assert db.get(OutboxEvent, ready.id).status == 'published'
    assert db.query(ObservationConsumerInbox).count() == 1
