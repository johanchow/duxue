"""Store confirmed Ward expression and review aspects by version.

Revision ID: 20261023_27
Revises: 20261022_26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20261023_27"
down_revision = "20261022_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "self_review_versions" not in existing:
        op.create_table(
            "self_review_versions",
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("review_id", sa.Uuid(as_uuid=False), sa.ForeignKey("self_reviews.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("raw_expression", sa.Text(), nullable=False),
            sa.Column("source_message_id", sa.Uuid(as_uuid=False), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("review_id", "version", name="uq_self_review_version"),
        )
        op.create_index("ix_self_review_versions_review_id", "self_review_versions", ["review_id"])
    if "self_review_aspects" not in existing:
        op.create_table(
            "self_review_aspects",
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("review_id", sa.Uuid(as_uuid=False), sa.ForeignKey("self_reviews.id"), nullable=False),
            sa.Column("review_version", sa.Integer(), nullable=False),
            sa.Column("dimension", sa.String(length=32), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("source_quote", sa.Text(), nullable=False),
            sa.Column("task_ref", sa.String(length=120), nullable=True),
            sa.Column("topic_ref", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_self_review_aspects_review_id", "self_review_aspects", ["review_id"])
        op.create_index("ix_self_review_aspects_dimension", "self_review_aspects", ["dimension"])


def downgrade() -> None:
    existing = set(inspect(op.get_bind()).get_table_names())
    if "self_review_aspects" in existing:
        op.drop_table("self_review_aspects")
    if "self_review_versions" in existing:
        op.drop_table("self_review_versions")
