"""Add revocable Ward App session versions.

Revision ID: 20260823_05
Revises: 20260823_04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260823_05"
down_revision = "20260823_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    column = sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ward_credentials", recreate="always") as batch:
            batch.add_column(column)
    else:
        op.add_column("ward_credentials", column)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ward_credentials", recreate="always") as batch:
            batch.drop_column("session_version")
    else:
        op.drop_column("ward_credentials", "session_version")
