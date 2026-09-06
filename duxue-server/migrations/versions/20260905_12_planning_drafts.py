"""Add optimistic plan drafts for planning workflow."""
from alembic import op
import sqlalchemy as sa

revision = "20260905_12"
down_revision = "20260905_11"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("daily_schedules", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "plan_drafts",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("base_schedule_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("pending_fields", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ward_id", "plan_date", name="uq_plan_draft_ward_date"),
    )
    op.create_index("ix_plan_drafts_ward_id", "plan_drafts", ["ward_id"])
    op.create_index("ix_plan_drafts_plan_date", "plan_drafts", ["plan_date"])
    op.create_index("ix_plan_drafts_status", "plan_drafts", ["status"])

def downgrade() -> None:
    op.drop_index("ix_plan_drafts_status", table_name="plan_drafts")
    op.drop_index("ix_plan_drafts_plan_date", table_name="plan_drafts")
    op.drop_index("ix_plan_drafts_ward_id", table_name="plan_drafts")
    op.drop_table("plan_drafts")
    op.drop_column("daily_schedules", "version")
