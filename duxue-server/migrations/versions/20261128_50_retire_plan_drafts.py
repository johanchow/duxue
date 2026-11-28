"""Remove online plan drafts after moving voluntary challenges to Study."""

import sqlalchemy as sa
from alembic import op

revision = "20261128_50"
down_revision = "20261128_49"
branch_labels = depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("plan_drafts"):
        op.drop_table("plan_drafts")


def downgrade():
    op.create_table(
        "plan_drafts",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("user_wards.id"),
            nullable=False,
        ),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("base_schedule_version", sa.Integer(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("pending_fields", sa.JSON(), nullable=False),
        sa.Column("working_state", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("ward_id", "plan_date", "status"):
        op.create_index("ix_plan_drafts_" + column, "plan_drafts", [column])
    op.create_index(
        "uq_active_plan_draft_ward_date",
        "plan_drafts",
        ["ward_id", "plan_date"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
