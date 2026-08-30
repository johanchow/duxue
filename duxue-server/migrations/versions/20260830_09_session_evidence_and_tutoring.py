"""Add explicit session evidence links and bounded tutoring conversations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260830_09"
down_revision = "20260830_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The preceding convergence migration created an empty target schema.  The
    # obsolete messages table has no production data and is replaced by a
    # conversation parent plus messages, with no database-level cascade.
    # Revision 08 intentionally builds from current ORM metadata.  On a fresh
    # install of later source it has already created the final tables, so this
    # compatibility revision becomes a no-op.  Existing 08 databases still
    # contain the former study_messages table and follow the conversion below.
    if "study_messages" not in set(inspect(op.get_bind()).get_table_names()):
        return
    op.drop_table("study_messages")
    op.create_table(
        "tutoring_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("ward_id", sa.String(length=36), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("study_session_id", sa.String(length=36), sa.ForeignKey("study_sessions.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("study_session_id", name="uq_tutoring_session_study_session"),
    )
    op.create_index("ix_tutoring_sessions_ward_id", "tutoring_sessions", ["ward_id"])
    op.create_index("ix_tutoring_sessions_study_session_id", "tutoring_sessions", ["study_session_id"])
    op.create_table(
        "tutoring_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tutoring_session_id", sa.String(length=36), sa.ForeignKey("tutoring_sessions.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_stuck_point", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tutoring_messages_tutoring_session_id", "tutoring_messages", ["tutoring_session_id"])
    op.add_column("frames", sa.Column("study_session_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_frames_study_session_id", "frames", "study_sessions", ["study_session_id"], ["id"])
    op.create_index("ix_frames_study_session_id", "frames", ["study_session_id"])
    op.add_column("behavior_segments", sa.Column("study_session_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_behavior_segments_study_session_id", "behavior_segments", "study_sessions", ["study_session_id"], ["id"])
    op.create_index("ix_behavior_segments_study_session_id", "behavior_segments", ["study_session_id"])


def downgrade() -> None:
    raise RuntimeError("The converged empty-database schema is intentionally not reversible")
