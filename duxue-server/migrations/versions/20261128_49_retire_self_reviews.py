"""Remove retired student self-review data; objective evening reports are independent."""

from pathlib import Path
from runpy import run_path

import sqlalchemy as sa
from alembic import op

revision = "20261128_49"
down_revision = "20261128_48"
branch_labels = depends_on = None


def upgrade():
    names = sa.inspect(op.get_bind()).get_table_names()
    for table in ("self_review_aspects", "self_review_versions", "self_reviews"):
        if table in names:
            op.drop_table(table)


def downgrade():
    op.create_table(
        "self_reviews",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("user_wards.id"),
            nullable=False,
        ),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("feeling", sa.String(40), nullable=False),
        sa.Column("reflection", sa.Text()),
        sa.Column("timeline_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ward_id", "review_date"),
    )
    op.create_index("ix_self_reviews_ward_id", "self_reviews", ["ward_id"])
    op.create_index("ix_self_reviews_review_date", "self_reviews", ["review_date"])
    run_path(str(Path(__file__).with_name("20261023_27_self_review_versions.py")))[
        "upgrade"
    ]()
