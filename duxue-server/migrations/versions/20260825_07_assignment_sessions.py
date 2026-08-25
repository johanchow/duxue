"""Allow study sessions to start from tasks outside a daily plan.

Revision ID: 20260825_07
Revises: 20260823_06
"""
from alembic import op
import sqlalchemy as sa


revision = "20260825_07"
down_revision = "20260823_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("study_sessions", recreate="always") as batch:
        batch.alter_column("plan_item_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("assignment_id", sa.String(36), sa.ForeignKey("assignments.id"), nullable=True))
        batch.create_index("ix_study_sessions_assignment_id", ["assignment_id"])


def downgrade() -> None:
    with op.batch_alter_table("study_sessions", recreate="always") as batch:
        batch.drop_index("ix_study_sessions_assignment_id")
        batch.drop_column("assignment_id")
        batch.alter_column("plan_item_id", existing_type=sa.String(36), nullable=False)
