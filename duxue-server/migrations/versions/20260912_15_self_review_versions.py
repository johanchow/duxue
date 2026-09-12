"""Version mutable self reviews before publishing versioned facts.

Revision ID: 20260912_15
Revises: 20260912_14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260912_15"
down_revision = "20260912_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns("self_reviews")}
    if "version" not in columns:
        op.add_column("self_reviews", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns("self_reviews")}
    if "version" in columns:
        op.drop_column("self_reviews", "version")
