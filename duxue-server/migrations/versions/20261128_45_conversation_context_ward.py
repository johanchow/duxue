"""Add optional read-only context_ward_id to conversation_threads for adult workbench."""

import sqlalchemy as sa
from alembic import op

revision = "20261128_45"
down_revision = "20261128_44"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {col["name"] for col in sa.inspect(bind).get_columns("conversation_threads")}
    if "context_ward_id" not in columns:
        op.add_column(
            "conversation_threads",
            sa.Column("context_ward_id", sa.Uuid(), nullable=True),
        )
    indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("conversation_threads")}
    if "ix_conversation_threads_context_ward_id" not in indexes:
        op.create_index(
            "ix_conversation_threads_context_ward_id",
            "conversation_threads",
            ["context_ward_id"],
        )


def downgrade():
    bind = op.get_bind()
    indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("conversation_threads")}
    if "ix_conversation_threads_context_ward_id" in indexes:
        op.drop_index("ix_conversation_threads_context_ward_id", table_name="conversation_threads")
    columns = {col["name"] for col in sa.inspect(bind).get_columns("conversation_threads")}
    if "context_ward_id" in columns:
        op.drop_column("conversation_threads", "context_ward_id")
