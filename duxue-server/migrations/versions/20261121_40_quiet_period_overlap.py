"""Enforce disjoint rest intervals even for writers outside the command handler."""

from alembic import op

revision = "20261121_40"
down_revision = "20261121_39"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute("""
            ALTER TABLE study_observation_quiet_periods
            ADD CONSTRAINT observation_quiet_no_overlap EXCLUDE USING gist
            (ward_id WITH =, tstzrange(starts_at, COALESCE(ended_at, scheduled_until), '[)') WITH &&)
        """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "observation_quiet_no_overlap", "study_observation_quiet_periods"
        )
