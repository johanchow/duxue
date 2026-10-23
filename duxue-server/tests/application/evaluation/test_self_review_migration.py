import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_review_migration_handles_fresh_and_existing_schemas(db_engine):
    migration = importlib.import_module("migrations.versions.20261023_27_self_review_versions")
    with db_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        # The historical schema rebuild may have already created current ORM tables.
        migration.upgrade()
        assert sa.inspect(connection).has_table("self_review_versions")
        assert sa.inspect(connection).has_table("self_review_aspects")

        # Existing databases instead need both tables created incrementally.
        migration.downgrade()
        assert not sa.inspect(connection).has_table("self_review_versions")
        migration.upgrade()
        assert sa.inspect(connection).has_table("self_review_versions")
        assert sa.inspect(connection).has_table("self_review_aspects")
