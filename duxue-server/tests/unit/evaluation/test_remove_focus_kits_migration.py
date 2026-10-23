from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_focus_kit_migration_handles_existing_and_fresh_schemas(db_engine):
    migration = importlib.import_module("migrations.versions.20261022_26_remove_focus_kits")

    with db_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        # Fresh installations built from current metadata already lack the table.
        migration.upgrade()
        assert not sa.inspect(connection).has_table("focus_kits")

        # Existing installations have the legacy table and data to retire.
        migration.downgrade()
        assert sa.inspect(connection).has_table("focus_kits")
        migration.upgrade()
        assert not sa.inspect(connection).has_table("focus_kits")
