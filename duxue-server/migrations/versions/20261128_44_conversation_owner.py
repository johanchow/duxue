"""Enforce exclusive Ward/Guardian ownership for every conversation."""

import sqlalchemy as sa
from alembic import op

revision = "20261128_44"
down_revision = "20261128_43"
branch_labels = depends_on = None
depends_on = None


def upgrade():
    constraints = sa.inspect(op.get_bind()).get_check_constraints(
        "conversation_threads"
    )
    if not any(c["name"] == "ck_conversation_one_owner" for c in constraints):
        op.create_check_constraint(
            "ck_conversation_one_owner",
            "conversation_threads",
            "(ward_id IS NULL) <> (guardian_id IS NULL)",
        )


def downgrade():
    op.drop_constraint(
        "ck_conversation_one_owner", "conversation_threads", type_="check"
    )
