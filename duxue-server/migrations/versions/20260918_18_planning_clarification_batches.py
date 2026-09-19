"""Persist durable Planning clarification batches.

Revision ID: 20260918_18
Revises: 20260914_17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260918_18"
down_revision = "20260914_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("plan_drafts")}
    if "working_state" not in columns:
        op.add_column(
            "plan_drafts",
            sa.Column("working_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("plan_drafts")}
    if "working_state" in columns:
        op.drop_column("plan_drafts", "working_state")
