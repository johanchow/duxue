"""Add durable companion coordinator metadata.

Revision ID: 20260905_11
Revises: 20260830_10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260905_11"
down_revision = "20260830_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 20260830_10 intentionally rebuilds an authorized empty database with
    # Base.metadata.create_all().  On a fresh upgrade it imports current ORM
    # metadata, so these tables may already exist before this revision runs.
    # On an existing database already at 20260830_10, this revision creates
    # them normally.
    if "conversation_threads" in inspect(op.get_bind()).get_table_names():
        return
    uuid = sa.Uuid(as_uuid=False)
    op.create_table(
        "conversation_threads",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("ward_id", uuid, sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("focus_run_ref", sa.String(length=100)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_threads_ward_id", "conversation_threads", ["ward_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("thread_id", uuid, sa.ForeignKey("conversation_threads.id"), nullable=False),
        sa.Column("ward_id", uuid, sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("agent_type", sa.String(length=20), nullable=False),
        sa.Column("run_ref", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("context_refs", sa.JSON(), nullable=False),
        sa.Column("graph_checkpoint_ref", sa.String(length=255)),
        sa.Column("graph_version", sa.String(length=40), nullable=False, server_default="v1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("thread_id", "run_ref", name="uq_agent_run_thread_ref"),
    )
    op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"])
    op.create_index("ix_agent_runs_ward_id", "agent_runs", ["ward_id"])
    op.create_index("ix_agent_runs_agent_type", "agent_runs", ["agent_type"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("run_id", uuid, sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("checkpoint_ref", sa.String(length=255), nullable=False),
        sa.Column("graph_version", sa.String(length=40), nullable=False),
        sa.Column("state_digest", sa.String(length=128), nullable=False),
        sa.Column("settlement_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "checkpoint_ref", name="uq_agent_checkpoint_run_ref"),
    )
    op.create_index("ix_agent_checkpoints_run_id", "agent_checkpoints", ["run_id"])
    op.create_table(
        "agent_traces",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("thread_id", uuid, sa.ForeignKey("conversation_threads.id"), nullable=False),
        sa.Column("run_id", uuid, sa.ForeignKey("agent_runs.id")),
        sa.Column("route_target", sa.String(length=20), nullable=False),
        sa.Column("route_mode", sa.String(length=20), nullable=False),
        sa.Column("route_reason", sa.String(length=120), nullable=False),
        sa.Column("context_refs", sa.JSON(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(length=40)),
        sa.Column("model_version", sa.String(length=100)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_traces_thread_id", "agent_traces", ["thread_id"])
    op.create_index("ix_agent_traces_run_id", "agent_traces", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_traces_run_id", table_name="agent_traces")
    op.drop_index("ix_agent_traces_thread_id", table_name="agent_traces")
    op.drop_table("agent_traces")
    op.drop_index("ix_agent_checkpoints_run_id", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_type", table_name="agent_runs")
    op.drop_index("ix_agent_runs_ward_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_thread_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_conversation_threads_ward_id", table_name="conversation_threads")
    op.drop_table("conversation_threads")
