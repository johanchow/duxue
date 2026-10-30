"""Retain companion history behind a Ward visibility generation.

Revision ID: 20261030_30
Revises: 20261029_29
"""
import sqlalchemy as sa
from alembic import op

revision = "20261030_30"
down_revision = "20261029_29"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table in ("user_wards", "conversation_threads"):
        if "history_generation" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("history_generation", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    for table in ("conversation_threads", "user_wards"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("history_generation")
