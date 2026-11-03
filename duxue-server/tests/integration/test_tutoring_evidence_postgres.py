"""Migration33 and evidence erasure against disposable PostgreSQL."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from app.bootstrap.app import app
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.models import TutoringMessage, TutoringProblem
from tests.application.study.test_guardian_evidence import _evidence, _headers
from tests.integration.test_gateway_postgres import (  # noqa: F401
    migrated_engine,
    postgres_url,
)
from tests.support.factories import create_guardian, create_ward


def test_evidence_migration_preserves_old_messages_and_erasure_obeys_foreign_keys(
    migrated_engine,  # noqa: F811 - imported pytest fixture
):
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as db:
        guardian = create_guardian(db)
        ward = create_ward(db, guardian=guardian)
        problem, _tutor, messages = _evidence(db, ward)
        db.commit()
        ward_id, problem_id = ward.id, problem.id
        message_ids = [m.id for m in messages]
        headers = _headers(guardian)
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261104_33_tutoring_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("evidence_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        migrated_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
        assert "problem_id" not in {
            column["name"]
            for column in inspect(connection).get_columns("tutoring_messages")
        }
        migration.upgrade()
    with factory() as db:
        assert db.get(TutoringProblem, problem_id) is not None
        rows = (
            db.query(TutoringMessage).filter(TutoringMessage.id.in_(message_ids)).all()
        )
        assert len(rows) == 4 and all(row.problem_id is None for row in rows)
        # Restore known references only for this test; production does not backfill them.
        for row in rows:
            row.problem_id = problem_id
        db.commit()

        def database():
            yield db

        app.dependency_overrides[get_db] = database
        try:
            with TestClient(app) as client:
                assert (
                    client.delete(f"/wards/{ward_id}/data", headers=headers).status_code
                    == 204
                )
            assert db.query(TutoringProblem).filter_by(id=problem_id).count() == 0
            assert (
                db.query(TutoringMessage)
                .filter(TutoringMessage.id.in_(message_ids))
                .count()
                == 0
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
