"""Bind shown work-product messages to their problem; never infer old associations."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_33"
down_revision = "20261103_32"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tutoring_messages",
        sa.Column("problem_id", sa.Uuid(as_uuid=False), nullable=True),
    )
    op.add_column(
        "tutoring_messages", sa.Column("evidence_kind", sa.String(20), nullable=True)
    )
    op.create_foreign_key(
        "fk_tutoring_message_problem",
        "tutoring_messages",
        "tutoring_problems",
        ["problem_id"],
        ["id"],
    )
    op.create_index(
        "ix_tutoring_messages_problem_id", "tutoring_messages", ["problem_id"]
    )


def downgrade():
    op.drop_index("ix_tutoring_messages_problem_id", table_name="tutoring_messages")
    op.drop_constraint(
        "fk_tutoring_message_problem", "tutoring_messages", type_="foreignkey"
    )
    op.drop_column("tutoring_messages", "evidence_kind")
    op.drop_column("tutoring_messages", "problem_id")
