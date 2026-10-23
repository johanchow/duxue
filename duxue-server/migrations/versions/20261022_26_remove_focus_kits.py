"""Remove the retired focus kit store.

Revision ID: 20261022_26
Revises: 20261010_25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20261022_26"
down_revision = "20261010_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The historical empty-schema rebuild uses current ORM metadata, so a
    # fresh install may already lack this table at the previous revision.
    if inspect(op.get_bind()).has_table("focus_kits"):
        op.drop_table("focus_kits")


def downgrade() -> None:
    op.create_table(
        "focus_kits",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_focus_kits_ward_id", "focus_kits", ["ward_id"])
    op.create_index("ix_focus_kits_review_date", "focus_kits", ["review_date"])
