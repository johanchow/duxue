"""Add the tutoring problem table that owns the answer state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261009_24"
down_revision = "20261007_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "tutoring_problems" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "tutoring_problems",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("tutoring_session_id", sa.Uuid(as_uuid=False), sa.ForeignKey("tutoring_sessions.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("solution_state", sa.String(length=20), nullable=False),
        sa.Column("substantive_attempts", sa.Integer(), nullable=False),
        sa.Column("no_progress_streak", sa.Integer(), nullable=False),
        sa.Column("hints_given", sa.Integer(), nullable=False),
        sa.Column("answer_requested", sa.Boolean(), nullable=False),
        sa.Column("last_turn_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tutoring_problems_tutoring_session_id", "tutoring_problems", ["tutoring_session_id"])
    op.create_index("ix_tutoring_problems_status", "tutoring_problems", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tutoring_problems_status", table_name="tutoring_problems")
    op.drop_index("ix_tutoring_problems_tutoring_session_id", table_name="tutoring_problems")
    op.drop_table("tutoring_problems")
