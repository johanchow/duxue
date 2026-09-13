"""Add renewable, session-bound Ward credentials.

Revision ID: 20260913_16
Revises: 20260912_15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260913_16"
down_revision = "20260912_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "ward_refresh_tokens" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "ward_refresh_tokens",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_ward_refresh_tokens_ward_id", "ward_refresh_tokens", ["ward_id"])


def downgrade() -> None:
    if "ward_refresh_tokens" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_ward_refresh_tokens_ward_id", table_name="ward_refresh_tokens")
    op.drop_table("ward_refresh_tokens")
