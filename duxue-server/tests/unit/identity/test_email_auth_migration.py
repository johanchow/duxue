"""The new auth migration must work for old schemas and empty-schema rebuilds."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.infrastructure.persistence.database import Base
from app.infrastructure.persistence.models import EmailAuthChallenge, EmailAuthFailure


def _upgrade(connection):
    path = Path(__file__).resolve().parents[3] / "migrations/versions/20261024_28_email_code_auth.py"
    spec = importlib.util.spec_from_file_location("email_auth_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


def test_migration_replaces_password_column():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE user_guardians (id VARCHAR(36) PRIMARY KEY, name VARCHAR(100), email VARCHAR(255), password_hash VARCHAR(255), role VARCHAR(20))"))
        _upgrade(connection)
        inspector = sa.inspect(connection)
        assert "password_hash" not in {column["name"] for column in inspector.get_columns("user_guardians")}
        assert inspector.has_table("email_auth_challenges")
        assert inspector.has_table("email_auth_failures")


def test_migration_accepts_fresh_orm_schema():
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        _upgrade(connection)
        assert sa.inspect(connection).has_table(EmailAuthChallenge.__tablename__)
        assert sa.inspect(connection).has_table(EmailAuthFailure.__tablename__)
