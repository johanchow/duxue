"""Add durable companion idempotency, stream, and outbox-delivery metadata.

Revision ID: 20260912_14
Revises: 20260907_13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260912_14"
down_revision = "20260907_13"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    uuid = sa.Uuid(as_uuid=False)
    additions = (
        ("attempt", sa.Column("attempt", sa.Integer(), nullable=False, server_default="1")),
        ("current_turn_id", sa.Column("current_turn_id", uuid)),
        ("deadline_at", sa.Column("deadline_at", sa.DateTime(timezone=True))),
        ("cancelled_at", sa.Column("cancelled_at", sa.DateTime(timezone=True))),
        ("failure", sa.Column("failure", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("outcome", sa.Column("outcome", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("policy_version", sa.Column("policy_version", sa.String(length=40), nullable=False, server_default="v1")),
    )
    for name, column in additions:
        if not _has_column("agent_runs", name):
            op.add_column("agent_runs", column)
    if not _has_column("outbox_events", "last_error"):
        op.add_column("outbox_events", sa.Column("last_error", sa.String(length=500)))

    tables = set(inspect(op.get_bind()).get_table_names())
    if "companion_commands" not in tables:
        op.create_table(
            "companion_commands",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("ward_id", uuid, sa.ForeignKey("user_wards.id"), nullable=False),
            sa.Column("thread_id", uuid, sa.ForeignKey("conversation_threads.id")),
            sa.Column("payload_digest", sa.String(length=64), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_companion_commands_ward_id", "companion_commands", ["ward_id"])
    if "agent_stream_events" not in tables:
        op.create_table(
            "agent_stream_events",
            sa.Column("id", uuid, primary_key=True),
            sa.Column("run_id", uuid, sa.ForeignKey("agent_runs.id"), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("policy_version", sa.String(length=40), nullable=False, server_default="v1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "attempt", "sequence", name="uq_agent_stream_sequence"),
        )
        op.create_index("ix_agent_stream_events_run_id", "agent_stream_events", ["run_id"])


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "agent_stream_events" in tables:
        op.drop_index("ix_agent_stream_events_run_id", table_name="agent_stream_events")
        op.drop_table("agent_stream_events")
    if "companion_commands" in tables:
        op.drop_index("ix_companion_commands_ward_id", table_name="companion_commands")
        op.drop_table("companion_commands")
    if _has_column("outbox_events", "last_error"):
        op.drop_column("outbox_events", "last_error")
    for name in ("policy_version", "outcome", "failure", "cancelled_at", "deadline_at", "current_turn_id", "attempt"):
        if _has_column("agent_runs", name):
            op.drop_column("agent_runs", name)
