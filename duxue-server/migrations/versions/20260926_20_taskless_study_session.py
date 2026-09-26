"""Allow a study session that is not bound to a confirmed task."""
import sqlalchemy as sa
from alembic import op

revision = "20260926_20"
down_revision = "20260920_19"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("study_sessions", "task_id", existing_type=sa.Uuid(), nullable=True)


def downgrade():
    op.alter_column("study_sessions", "task_id", existing_type=sa.Uuid(), nullable=False)
