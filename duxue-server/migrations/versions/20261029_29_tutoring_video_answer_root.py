"""Add Tutoring video answer aggregate root.

Revision ID: 20261029_29
Revises: 20261024_28
"""

import sqlalchemy as sa
from alembic import op

revision = "20261029_29"
down_revision = "20261024_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("tutoring_video_answers"):
        return
    op.create_table(
        "tutoring_video_answers",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("request_command_id", sa.String(100), nullable=False),
        sa.Column("question_ref", sa.String(100), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("proposed_outline_version", sa.Integer(), nullable=True),
        sa.Column("confirmed_outline_version", sa.Integer(), nullable=True),
        sa.Column("artifact_version", sa.Integer(), nullable=True),
        sa.Column("revision_base_version", sa.Integer(), nullable=True),
        sa.Column("published_versions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ward_id", "request_command_id", name="uq_video_answer_ward_command"),
        sa.CheckConstraint("duration_seconds IN (180, 300, 360)", name="ck_video_answer_duration"),
        sa.CheckConstraint("status IN ('awaiting_outline', 'producing', 'ready', 'failed')", name="ck_video_answer_status"),
    )
    op.create_index("ix_tutoring_video_answers_ward_id", "tutoring_video_answers", ["ward_id"])


def downgrade() -> None:
    op.drop_index("ix_tutoring_video_answers_ward_id", table_name="tutoring_video_answers")
    op.drop_table("tutoring_video_answers")
