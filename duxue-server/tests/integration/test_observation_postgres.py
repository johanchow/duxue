"""Commit ordering, rollback and immutable evidence on a disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy.orm import sessionmaker

from app.infrastructure.persistence.evidence_repository import (
    AcceptedEvidenceQuery,
    record_accepted_evidence,
)
from tests.integration.test_gateway_postgres import (  # noqa: F401
    migrated_engine,
    postgres_url,
)
from tests.unit.behavior.test_evidence_journal import make_frame


def test_receipt_allocation_serializes_commit_not_capture_order(migrated_engine):  # noqa: F811
    factory = sessionmaker(bind=migrated_engine)
    allocated = Event()
    release = Event()
    second_started = Event()

    def first():
        with factory() as db:
            frame = make_frame(db)
            sequence = record_accepted_evidence(db, frame, 1)
            allocated.set()
            assert release.wait(5)
            db.commit()
            return sequence

    def second():
        assert allocated.wait(5)
        with factory() as db:
            frame = make_frame(db)
            second_started.set()
            sequence = record_accepted_evidence(db, frame, 2)
            db.commit()
            return sequence

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first)
        b = pool.submit(second)
        assert second_started.wait(5)
        with factory() as db:
            # Neither the uncommitted receipt nor its counter is visible.
            rows, _, upper = AcceptedEvidenceQuery(db).list_accepted(
                system_scope=True, after=0
            )
            assert not rows
            assert upper == 0
        release.set()
        assert a.result() < b.result()
    with factory() as db:
        rows, _, upper = AcceptedEvidenceQuery(db).list_accepted(
            system_scope=True, after=0
        )
        assert [r.assignment_revision for r in rows] == [1, 2]
        assert len(rows) == upper == 2


def test_observation_migration_matches_model_columns(migrated_engine):  # noqa: F811
    from sqlalchemy import inspect
    from app.infrastructure.persistence.models import Base
    inspector = inspect(migrated_engine)
    names = {'accepted_evidence', 'observation_settings', 'observation_windows',
             'observation_jobs', 'observation_revisions', 'reflection_report_versions',
             'support_channels', 'help_offers'}
    for name in names:
        table = Base.metadata.tables[name]
        assert {c['name'] for c in inspector.get_columns(name)} == set(table.columns.keys())
