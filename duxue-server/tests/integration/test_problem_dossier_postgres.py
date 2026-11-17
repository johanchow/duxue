"""Migration 37 (`problem_dossiers`) and ward-scoped dossier erasure against disposable PostgreSQL."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from app.bootstrap.app import app
from app.infrastructure.persistence.database import get_db
from app.infrastructure.persistence.models import (
    ProblemDossierRecord,
    TutoringSession,
)
from tests.application.study.test_guardian_evidence import _evidence, _headers
from tests.integration.test_gateway_postgres import (  # noqa: F401
    migrated_engine,
    postgres_url,
)
from tests.support.factories import create_guardian, create_ward


def test_problem_dossiers_migration_roundtrip_and_ward_erasure_preserves_bank_dossiers(
    migrated_engine,  # noqa: F811
):
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    # Verify downgrade 37 -> 36 and upgrade 36 -> 37 cleanly
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261117_37_problem_dossiers.py"
    )
    spec = importlib.util.spec_from_file_location("dossier_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with (
        migrated_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
        assert "problem_dossiers" not in set(inspect(connection).get_table_names())
        assert "dossier_id" not in {
            c["name"] for c in inspect(connection).get_columns("tutoring_problems")
        }
        migration.upgrade()
        assert "problem_dossiers" in set(inspect(connection).get_table_names())

    with factory() as db:
        guardian = create_guardian(db)
        ward = create_ward(db, guardian=guardian)
        problem, _tutor, _messages = _evidence(db, ward)

        ward_dossier = ProblemDossierRecord(
            fingerprint="fp_ward_private_001",
            scope="ward",
            owner_ward_id=ward.id,
            subject="math",
            tier="T1",
            stem={"subject": "math", "raw_text": "学生私有题"},
            approaches=[],
            invariants=[],
            scoring_points=[],
            final_answers={},
            confidence="medium",
            status="ready",
            evidence={},
            solver_version="dossier.v1",
        )
        bank_dossier = ProblemDossierRecord(
            fingerprint="fp_bank_shared_001",
            scope="bank",
            owner_ward_id=None,
            subject="math",
            tier="T2",
            stem={"subject": "math", "raw_text": "授权公共题库题"},
            approaches=[],
            invariants=[],
            scoring_points=[],
            final_answers={"(1)": "42"},
            confidence="high",
            status="ready",
            evidence={},
            solver_version="dossier.v1",
        )
        db.add_all([ward_dossier, bank_dossier])
        db.flush()
        problem.dossier_id = ward_dossier.id
        db.commit()

        ward_id = ward.id
        ward_dossier_id = ward_dossier.id
        bank_dossier_id = bank_dossier.id
        headers = _headers(guardian)

        def database():
            yield db

        app.dependency_overrides[get_db] = database
        try:
            with TestClient(app) as client:
                resp = client.delete(f"/wards/{ward_id}/data", headers=headers)
                assert resp.status_code == 204

            db.expire_all()
            # Ward's tutoring problems and `ward`-scoped dossier are physically erased
            assert db.query(TutoringSession).filter_by(ward_id=ward_id).count() == 0
            assert db.query(ProblemDossierRecord).filter_by(id=ward_dossier_id).count() == 0
            # Global `bank` dossier (zero PII) is untouched!
            assert db.query(ProblemDossierRecord).filter_by(id=bank_dossier_id).count() == 1
        finally:
            app.dependency_overrides.pop(get_db, None)
