"""Replace legacy answer unlocking with evidence-driven tutoring state."""

import sqlalchemy as sa
from alembic import op

revision = "20261010_25"
down_revision = "20261009_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tutoring_problems SET status = 'submitted' WHERE status = 'solved'")
    with op.batch_alter_table("tutoring_problems") as batch:
        batch.add_column(sa.Column("active_subgoal", sa.Text(), nullable=True))
        batch.add_column(sa.Column("evidence_summary", sa.Text(), nullable=True))
        batch.drop_column("solution_state")
        batch.drop_column("no_progress_streak")
        batch.drop_column("answer_requested")


def downgrade() -> None:
    with op.batch_alter_table("tutoring_problems") as batch:
        batch.add_column(sa.Column("solution_state", sa.String(length=20), nullable=False, server_default="locked"))
        batch.add_column(sa.Column("no_progress_streak", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("answer_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.drop_column("evidence_summary")
        batch.drop_column("active_subgoal")
    op.execute("UPDATE tutoring_problems SET solution_state = 'solved', status = 'solved' WHERE status = 'submitted'")
