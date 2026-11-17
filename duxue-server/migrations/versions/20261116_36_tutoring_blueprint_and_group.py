"""Server-private SolutionBlueprint and multi-subproblem group context on tutoring_problems."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_36"
down_revision = "20261112_35"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tutoring_problems",
        sa.Column("internal_blueprint", sa.JSON(), nullable=True),
    )
    op.add_column(
        "tutoring_problems",
        sa.Column("group_context", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("tutoring_problems", "group_context")
    op.drop_column("tutoring_problems", "internal_blueprint")
