"""Remove Ward PIN credentials in favor of one-time binding codes.

Revision ID: 20260823_06
Revises: 20260823_05
"""
from alembic import op
import sqlalchemy as sa


revision = "20260823_06"
down_revision = "20260823_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ward_credentials", recreate="always") as batch:
            batch.drop_column("pin_hash")
    else:
        op.drop_column("ward_credentials", "pin_hash")


def downgrade() -> None:
    column = sa.Column("pin_hash", sa.String(255), nullable=False, server_default="")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ward_credentials", recreate="always") as batch:
            batch.add_column(column)
    else:
        op.add_column("ward_credentials", column)
