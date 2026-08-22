"""Add the one-day-story MVP domain.

Revision ID: 20260822_03
Revises: 20260804_02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260822_03"
down_revision = "20260804_02"
branch_labels = None
depends_on = None

def _id_table(name, *columns):
    op.create_table(name, sa.Column("id", sa.String(36), primary_key=True), *columns)

def upgrade():
    op.create_table("ward_credentials", sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), primary_key=True), sa.Column("pin_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _id_table("ward_invites", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("code", sa.String(8), nullable=False, unique=True), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)))
    _id_table("assignments", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("title", sa.String(300), nullable=False), sa.Column("details", sa.Text()), sa.Column("due_date", sa.Date()), sa.Column("source", sa.String(20), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _id_table("daily_plans", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("plan_date", sa.Date(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("tenant_id", "ward_id", "plan_date"))
    _id_table("plan_items", sa.Column("plan_id", sa.String(36), sa.ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False), sa.Column("assignment_id", sa.String(36), sa.ForeignKey("assignments.id")), sa.Column("title", sa.String(300), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("planned_minutes", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False))
    _id_table("study_sessions", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("plan_item_id", sa.String(36), sa.ForeignKey("plan_items.id"), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("active_seconds", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False))
    _id_table("study_messages", sa.Column("session_id", sa.String(36), sa.ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("is_stuck_point", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    _id_table("self_reviews", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("review_date", sa.Date(), nullable=False), sa.Column("feeling", sa.String(40), nullable=False), sa.Column("reflection", sa.Text()), sa.Column("timeline_json", sa.JSON(), nullable=False), sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("tenant_id", "ward_id", "review_date"))
    _id_table("focus_kits", sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False), sa.Column("ward_id", sa.String(36), sa.ForeignKey("user_wards.id", ondelete="CASCADE"), nullable=False), sa.Column("review_date", sa.Date(), nullable=False), sa.Column("advice", sa.Text(), nullable=False), sa.Column("saved_at", sa.DateTime(timezone=True)))

def downgrade():
    for name in ("focus_kits", "self_reviews", "study_messages", "study_sessions", "plan_items", "daily_plans", "assignments", "ward_invites", "ward_credentials"): op.drop_table(name)
