"""Add aggregate identities and lifecycle fields for Memory."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260907_13"
down_revision = "20260905_12"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = inspect(op.get_bind())
    episodic_columns = {item["name"] for item in inspector.get_columns("episodic_memories")}
    for name, column in (
        ("memory_type", sa.Column("memory_type", sa.String(80), nullable=False, server_default="legacy")),
        ("aggregate_ref", sa.Column("aggregate_ref", sa.String(120), nullable=False, server_default="legacy")),
        ("aggregate_version", sa.Column("aggregate_version", sa.Integer(), nullable=False, server_default="1")),
        ("hot_until", sa.Column("hot_until", sa.DateTime(timezone=True))),
        ("expires_at", sa.Column("expires_at", sa.DateTime(timezone=True))),
        ("archived_at", sa.Column("archived_at", sa.DateTime(timezone=True))),
        ("policy_version", sa.Column("policy_version", sa.String(40), nullable=False, server_default="v1")),
    ):
        if name not in episodic_columns:
            op.add_column("episodic_memories", column)
    indexes = {item["name"] for item in inspector.get_indexes("episodic_memories")}
    if "ix_episodic_memories_memory_type" not in indexes:
        op.create_index("ix_episodic_memories_memory_type", "episodic_memories", ["memory_type"])
    episodic_unique = {item["name"] for item in inspector.get_unique_constraints("episodic_memories")}
    if "uq_episodic_memory_aggregate" not in episodic_unique:
        op.create_unique_constraint("uq_episodic_memory_aggregate", "episodic_memories", ["memory_type", "aggregate_ref", "aggregate_version"])
    signal_columns = {item["name"] for item in inspector.get_columns("derived_signals")}
    if "dimension_key" not in signal_columns:
        op.add_column("derived_signals", sa.Column("dimension_key", sa.String(120), nullable=False, server_default=""))
    signal_unique = {item["name"] for item in inspector.get_unique_constraints("derived_signals")}
    if "uq_derived_signal_identity" not in signal_unique:
        op.create_unique_constraint("uq_derived_signal_identity", "derived_signals", ["ward_id", "signal_type", "scope", "dimension_key"])
    event_unique = {item["name"] for item in inspector.get_unique_constraints("derived_signal_events")}
    if "uq_derived_signal_event_role" not in event_unique:
        if "uq_derived_signal_event" in event_unique:
            op.drop_constraint("uq_derived_signal_event", "derived_signal_events", type_="unique")
        op.create_unique_constraint("uq_derived_signal_event_role", "derived_signal_events", ["derived_signal_id", "learning_event_id", "role"])

def downgrade() -> None:
    op.drop_constraint("uq_derived_signal_event_role", "derived_signal_events", type_="unique")
    op.create_unique_constraint("uq_derived_signal_event", "derived_signal_events", ["derived_signal_id", "learning_event_id"])
    op.drop_constraint("uq_derived_signal_identity", "derived_signals", type_="unique")
    op.drop_column("derived_signals", "dimension_key")
    op.drop_constraint("uq_episodic_memory_aggregate", "episodic_memories", type_="unique")
    op.drop_index("ix_episodic_memories_memory_type", table_name="episodic_memories")
    for name in ("policy_version", "archived_at", "expires_at", "hot_until", "aggregate_version", "aggregate_ref", "memory_type"):
        op.drop_column("episodic_memories", name)
