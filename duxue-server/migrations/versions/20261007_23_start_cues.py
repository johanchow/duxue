"""Add the study start-cue invitation table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261007_23"
down_revision = "20261007_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "start_cues" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "start_cues",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("due_task_id", sa.Uuid(as_uuid=False), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("schedule_id", sa.Uuid(as_uuid=False), sa.ForeignKey("daily_schedules.id"), nullable=False),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("earlier_task_ids", sa.JSON(), nullable=False),
        sa.Column("current_session_id", sa.Uuid(as_uuid=False), sa.ForeignKey("study_sessions.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scene_label", sa.String(length=32), nullable=True),
        sa.Column("gap_reason", sa.String(length=32), nullable=True),
        sa.Column("snooze_count", sa.Integer(), nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_start_cues_ward_id", "start_cues", ["ward_id"])
    op.create_index("ix_start_cues_due_task_id", "start_cues", ["due_task_id"])
    op.create_index("ix_start_cues_schedule_id", "start_cues", ["schedule_id"])
    op.create_index("ix_start_cues_status", "start_cues", ["status"])
    op.create_index(
        "uq_open_start_cue_ward",
        "start_cues",
        ["ward_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','held','ready','presented')"),
    )


def downgrade() -> None:
    if "start_cues" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("uq_open_start_cue_ward", table_name="start_cues")
    op.drop_index("ix_start_cues_status", table_name="start_cues")
    op.drop_index("ix_start_cues_schedule_id", table_name="start_cues")
    op.drop_index("ix_start_cues_due_task_id", table_name="start_cues")
    op.drop_index("ix_start_cues_ward_id", table_name="start_cues")
    op.drop_table("start_cues")
