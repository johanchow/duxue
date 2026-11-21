"""Run with OBSERVATION_TEST_POSTGRES=1; each case rolls back on duxue-test."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility, digest
from app.agent_specs.definitions import use_definitions
from app.agent_specs.observation_contracts import IDS, provision, workflow_documents
from app.application.commands.behavior_observation import ObservationCommands
from app.application.commands.help_offers import HelpOfferCommands
from app.application.commands.observation_quiet import change_quiet
from app.infrastructure.persistence import models as m
from app.infrastructure.persistence.evidence_repository import record_accepted_evidence
from scripts.upgrade_observation_rules import upgrade
from tests.unit.behavior.test_evidence_journal import make_frame
from tests.unit.behavior.test_observation_config import bundle

T = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def postgres():
    if os.environ.get("OBSERVATION_TEST_POSTGRES") != "1":
        pytest.skip("requires explicit duxue-test opt-in")
    env_path = Path(__file__).resolve().parents[2] / ".env"
    url = make_url(dotenv_values(env_path)["DATABASE_URL"])
    assert url.database == "duxue-test" and url.get_backend_name() == "postgresql"
    engine = create_engine(url.set(drivername="postgresql+psycopg"))
    with engine.connect() as connection:
        tx = connection.begin()
        try:
            with Session(
                connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as db:
                yield db
        finally:
            tx.rollback()
    engine.dispose()


def configured_rules():
    source = bundle()
    for identifier in IDS:
        source["files"][f"agents/{identifier}.json"] = provision(
            identifier, model="fixture", prompt="fixture"
        )
    source["files"].update(workflow_documents())
    source["compatibility"] = contract_compatibility(source["files"])
    record = upgrade({"bundle": source, "digest": digest(source)})
    policy = record["bundle"]["files"]["policies/observation-support.json"]
    policy["groups"]["offer_help"][0]["min_continuous_seconds"] = 15
    return compile_bundle(record["bundle"])


def test_quiet_retries_and_early_return(postgres):
    db = postgres
    ward = make_frame(db, T).ward_id
    start = change_quiet(db, ward, "open", "start", 900, T, 0)
    extended = change_quiet(db, ward, "more", "extend", 300, T, 1)
    assert datetime.fromisoformat(extended["effective_until"]) == T + timedelta(
        minutes=20
    )
    assert change_quiet(db, ward, "more", "extend", 300, T, 1) == extended
    with pytest.raises(HTTPException) as err:
        change_quiet(db, ward, "more", "extend", 60, T, 1)
    assert err.value.status_code == 409
    assert not change_quiet(
        db, ward, "back", "end", None, T + timedelta(seconds=10), 2
    )["active"]
    assert db.get(m.QuietPeriod, start["period_id"]).ended_at == T + timedelta(
        seconds=10
    )


def test_camera_to_invitation_and_rest_fence(postgres):
    db = postgres
    clock = T + timedelta(minutes=1)
    first = make_frame(db, T)
    ward, camera = first.ward_id, first.device_id
    frames = [first]
    for offset in (15, 30, 45):
        frame = m.Frame(
            ward_id=ward,
            device_id=camera,
            captured_at=T + timedelta(seconds=offset),
            purge_after=clock + timedelta(days=1),
        )
        db.add(frame)
        db.flush()
        frames.append(frame)
    for frame in frames:
        frame.oss_key = f"{ward}/{frame.id}.jpg"
        record_accepted_evidence(db, frame, 1)
    db.add(
        m.ObservationSettings(
            ward_id=ward, camera_id=camera, enabled=True, mode="enabled"
        )
    )
    channel = m.SupportChannel(
        ward_id=ward,
        enabled=True,
        handsfree=False,
        expires_at=clock + timedelta(seconds=45),
    )
    db.add(channel)
    db.flush()

    class Vision:
        def __call__(self, manifest):
            cells = []
            for frame in manifest["frames"]:
                t = datetime.fromisoformat(frame["at"])
                cells.append(
                    {
                        "start": t.isoformat(),
                        "end": (t + timedelta(seconds=15)).isoformat(),
                        "activity": "reading_material",
                        "evidence_frame_ids": [frame["id"]],
                        "rule_matches": [
                            {
                                "rule_id": r["id"],
                                "verdict": "matched",
                                "evidence_frame_ids": [frame["id"]],
                            }
                            for rules in manifest["rule_groups"].values()
                            for r in rules
                        ],
                    }
                )
            return {"cells": cells, "provenance": {"model": "fixture"}}

        def assess(self, payload):
            assert payload["requested_kind"] == "offer_help"
            return {
                "decision": "offer_help",
                "evidence_refs": [payload["frames"][-1]["id"]],
                "observed_basis": "fixture",
                "provenance": {},
            }

    with use_definitions(configured_rules().catalog):
        cmd = ObservationCommands(db, Vision(), lambda: clock)
        cmd.open_window(
            SimpleNamespace(
                ward_id=ward,
                payload={
                    "start": T.isoformat(),
                    "generation": 1,
                    "camera_id": camera,
                    "revision": 1,
                },
            )
        )

        def next_job(kind):
            job = db.query(m.ObservationJob).filter_by(ward_id=ward, kind=kind).one()
            job.status, job.token, job.lease_until = (
                "running",
                str(uuid4()),
                clock + timedelta(minutes=2),
            )
            db.flush()
            return job

        cmd.analyze(next_job("analyze"))
        cmd.publish_day(next_job("publish"))
        cmd.assess_support(next_job("assess"))
        day = db.query(m.ObservationDayRecord).filter_by(ward_id=ward).one()
        assert day.revision == 2
        offers = HelpOfferCommands(db, lambda: clock)
        offers.consider(day.id)
        invitation = offers.present(ward, channel.id)
        assert invitation["prompt_id"] == "offer_help"
        change_quiet(db, ward, "rest", "start", 1200, clock)
        assert offers.present(ward, channel.id) is None
        assert (
            db.get(m.HelpOfferRecord, invitation["offer_id"]).closed_reason
            == "quiet_period"
        )
        offers.consider(day.id)
        assert db.query(m.HelpOfferRecord).filter_by(ward_id=ward).count() == 1


def test_elapsed_rest_excludes_partial_slots_and_idempotent_end(postgres):
    from sqlalchemy.exc import IntegrityError

    from app.application.commands.observation_quiet import excluded_slots

    db = postgres
    ward = make_frame(db, T).ward_id
    change_quiet(db, ward, "rest", "start", 20, T + timedelta(seconds=4))
    assert excluded_slots(db, ward, T, T + timedelta(minutes=1)) == [
        T.isoformat(),
        (T + timedelta(seconds=15)).isoformat(),
    ]
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            m.QuietPeriod(
                ward_id=ward,
                starts_at=T + timedelta(seconds=10),
                scheduled_until=T + timedelta(seconds=30),
                version=2,
            )
        )
        db.flush()
    reply = change_quiet(db, ward, "end", "end", None, T + timedelta(seconds=60))
    assert not reply["active"]
    assert reply["ward_version"] == 1


def test_rule_contract_rejects_ambiguous_matches():
    from app.contexts.behavior_analysis.domain.observation import Cell
    from app.contexts.behavior_analysis.domain.reminder_rules import checked_matches

    manifest = {"rule_groups": {"offer_help": [{"id": "still"}], "invite_return": []}}
    cell = Cell(T, T + timedelta(seconds=15), "reading_material", ("frame",))
    row = {
        "start": T.isoformat(),
        "end": cell.end.isoformat(),
        "activity": cell.activity,
        "evidence_frame_ids": ["frame"],
        "rule_matches": [
            {
                "rule_id": "still",
                "verdict": "matched",
                "evidence_frame_ids": ["foreign"],
            }
        ],
    }
    with pytest.raises(ValueError, match="another slot"):
        checked_matches(manifest, [row], [cell])
    row["rule_matches"] = []
    with pytest.raises(ValueError, match="cover manifest"):
        checked_matches(manifest, [row], [cell])
    assert checked_matches(
        {**manifest, "quiet_slots": [T.isoformat()]}, [row], [cell]
    ) == {T: []}
