"""Map task rows onto pool / scheduled / completed / cancelled."""
import sqlalchemy as sa
from alembic import op

revision = "20260926_21"
down_revision = "20260926_20"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET status = 'scheduled'
            WHERE status IN ('open', 'pending') AND schedule_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET status = 'pool'
            WHERE status IN ('open', 'pending') AND schedule_id IS NULL
            """
        )
    )


def downgrade():
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET status = 'open'
            WHERE status IN ('pool', 'scheduled')
            """
        )
    )
