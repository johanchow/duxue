"""Add Ward-visible companion transcript journal.

Revision ID: 20260914_17
Revises: 20260913_16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260914_17"
down_revision = "20260913_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "companion_messages" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "companion_messages",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("thread_id", sa.Uuid(as_uuid=False), sa.ForeignKey("conversation_threads.id"), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=False), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("command_id", sa.Uuid(as_uuid=False), sa.ForeignKey("companion_commands.id"), nullable=False),
        sa.Column("turn_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("thread_version", sa.Integer(), nullable=False),
        sa.Column("author_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachment_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("interaction_ref", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("thread_id", "thread_version", name="uq_companion_messages_thread_version"),
        sa.UniqueConstraint("ward_id", "command_id", "author_type", name="uq_companion_messages_ward_command_author"),
        sa.UniqueConstraint("run_id", "turn_id", "attempt", "author_type", name="uq_companion_messages_run_turn_attempt_author"),
        sa.CheckConstraint("author_type IN ('ward', 'companion')", name="ck_companion_message_author"),
    )
    op.create_index("idx_companion_messages_ward_thread_version", "companion_messages", ["ward_id", "thread_id", "thread_version"])


def downgrade() -> None:
    if "companion_messages" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("idx_companion_messages_ward_thread_version", table_name="companion_messages")
    op.drop_table("companion_messages")
