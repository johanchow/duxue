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
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("study_sessions", "plan_item_id", existing_type=sa.String(36), nullable=True)
        op.add_column("study_sessions", sa.Column("assignment_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            "fk_study_sessions_assignment_id_assignments",
            "study_sessions",
            "assignments",
            ["assignment_id"],
            ["id"],
        )
        op.create_index("ix_study_sessions_assignment_id", "study_sessions", ["assignment_id"])
        return
    with op.batch_alter_table("study_sessions", recreate="always") as batch:
        batch.alter_column("plan_item_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("assignment_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_study_sessions_assignment_id_assignments", "assignments", ["assignment_id"], ["id"])
        batch.create_index("ix_study_sessions_assignment_id", ["assignment_id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_study_sessions_assignment_id", table_name="study_sessions")
        op.drop_constraint("fk_study_sessions_assignment_id_assignments", "study_sessions", type_="foreignkey")
        op.drop_column("study_sessions", "assignment_id")
        op.alter_column("study_sessions", "plan_item_id", existing_type=sa.String(36), nullable=False)
        return
    with op.batch_alter_table("study_sessions", recreate="always") as batch:
        batch.drop_index("ix_study_sessions_assignment_id")
        batch.drop_constraint("fk_study_sessions_assignment_id_assignments", type_="foreignkey")
        batch.drop_column("assignment_id")
        batch.alter_column("plan_item_id", existing_type=sa.String(36), nullable=False)
