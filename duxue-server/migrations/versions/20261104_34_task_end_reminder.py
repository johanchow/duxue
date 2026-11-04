"""Explicit task end reminders; historical estimates do not authorize reminders."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_34"
down_revision = "20261104_33"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("end_reminder_mode", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("tasks", "end_reminder_mode")
