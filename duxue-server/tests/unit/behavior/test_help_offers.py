from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.application.commands.help_offers import HelpOfferCommands
from app.infrastructure.persistence.models import (
    HelpOfferBudgetRecord,
    HelpOfferRecord,
    ObservationDayRecord,
    ObservationRevisionRecord,
    SupportChannel,
    SupportReceipt,
)
from tests.unit.behavior.test_observation import T
from tests.unit.behavior.test_observation_commands import setup


def scenario(db, mode="enabled"):
    frame, setting = setup(db)
    setting.mode = mode
    day = ObservationDayRecord(
        ward_id=frame.ward_id, local_date=T.date(), timezone="Asia/Shanghai", revision=1
    )
    db.add(day)
    db.flush()
    candidate = {
        "decision": "offer_help",
        "start": (T - timedelta(minutes=4)).isoformat(),
        "end": T.isoformat(),
        "observed_at": T.isoformat(),
        "fresh_until": (T + timedelta(seconds=120)).isoformat(),
        "assessment_version": "test",
        "evidence_refs": [frame.id],
    }
    db.add(
        ObservationRevisionRecord(
            day_id=day.id,
            revision=1,
            snapshot={
                "runs": [
                    {
                        "activity": "still_with_material",
                        "start": candidate["start"],
                        "end": candidate["end"],
                    }
                ],
                "candidates": [candidate],
            },
        )
    )
    channel = SupportChannel(
        ward_id=frame.ward_id,
        enabled=True,
        handsfree=False,
        expires_at=T + timedelta(seconds=45),
    )
    db.add(channel)
    db.commit()
    return frame, day, channel


def test_shadow_records_without_budget_or_presentation(db):
    frame, day, channel = scenario(db, "shadow")
    service = HelpOfferCommands(db, lambda: T)
    service.consider(day.id)
    db.commit()
    assert db.query(HelpOfferRecord).one().status == "shadow"
    assert db.query(HelpOfferBudgetRecord).count() == 0
    assert service.present(frame.ward_id, channel.id) is None


def test_duplicate_candidate_reserves_once_and_requires_actual_receipt(db):
    frame, day, channel = scenario(db)
    service = HelpOfferCommands(db, lambda: T)
    service.consider(day.id)
    service.consider(day.id)
    db.commit()
    assert db.query(HelpOfferBudgetRecord).one().reserved_count == 1
    offer = db.query(HelpOfferRecord).one()
    with pytest.raises(HTTPException):
        service.respond(
            frame.ward_id, offer.id, "accept_help", offer.version, str(uuid4())
        )
    receipt_id = str(uuid4())
    result = service.receipt(
        frame.ward_id,
        channel.id,
        offer_id=offer.id,
        receipt_id=receipt_id,
        medium="card_rendered",
        presented_at=T,
        expected_version=offer.version,
    )
    db.commit()
    assert (
        service.receipt(
            frame.ward_id,
            channel.id,
            offer_id=offer.id,
            receipt_id=receipt_id,
            medium="card_rendered",
            presented_at=T,
            expected_version=1,
        )
        == result
    )
    assert db.query(SupportReceipt).count() == 1
    command = str(uuid4())
    response = service.respond(
        frame.ward_id, offer.id, "accept_help", result["version"], command
    )
    db.commit()
    assert response["focus_composer"]
    assert (
        service.respond(
            frame.ward_id, offer.id, "accept_help", result["version"], command
        )
        == response
    )


def test_new_observation_missing_or_recovered_suppresses_offer(db):
    frame, day, channel = scenario(db)
    service = HelpOfferCommands(db, lambda: T)
    service.consider(day.id)
    db.commit()
    day.revision = 2
    db.add(
        ObservationRevisionRecord(
            day_id=day.id, revision=2, snapshot={"runs": [{"activity": "missing"}]}
        )
    )
    db.commit()
    assert service.present(frame.ward_id, channel.id) is None
    assert db.query(HelpOfferRecord).one().status == "expired"


def test_late_receipt_and_foreign_ward_cannot_present(db):
    frame, day, channel = scenario(db)
    service = HelpOfferCommands(db, lambda: T)
    service.consider(day.id)
    db.commit()
    offer = db.query(HelpOfferRecord).one()
    with pytest.raises(HTTPException):
        service.receipt(
            str(uuid4()),
            channel.id,
            offer_id=offer.id,
            receipt_id=str(uuid4()),
            medium="card_rendered",
            presented_at=T,
            expected_version=1,
        )
    late = HelpOfferCommands(db, lambda: T + timedelta(minutes=3))
    with pytest.raises(HTTPException):
        late.receipt(
            frame.ward_id,
            channel.id,
            offer_id=offer.id,
            receipt_id=str(uuid4()),
            medium="card_rendered",
            presented_at=T + timedelta(minutes=3),
            expected_version=1,
        )


def test_configuration_generation_invalidates_pending_invitation(db):
    from app.infrastructure.persistence.models import ObservationSettings
    frame, day, channel = scenario(db)
    service = HelpOfferCommands(db, lambda: T)
    service.consider(day.id)
    db.commit()
    setting = db.get(ObservationSettings, frame.ward_id)
    setting.generation += 1
    db.commit()
    assert service.present(frame.ward_id, channel.id) is None
