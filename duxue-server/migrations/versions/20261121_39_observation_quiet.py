"""Ward-owned quiet periods and retry receipts for camera invitations."""

from alembic import op
import sqlalchemy as sa

revision = "20261121_39"
down_revision = "20261120_38"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "study_observation_quiet_periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(),
            sa.ForeignKey("user_wards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("starts_at < scheduled_until"),
        sa.CheckConstraint(
            "ended_at IS NULL OR (ended_at >= starts_at AND ended_at <= scheduled_until)"
        ),
    )
    op.create_index(
        "ix_observation_quiet_latest",
        "study_observation_quiet_periods",
        ["ward_id", "starts_at"],
    )
    op.create_table(
        "study_observation_quiet_commands",
        sa.Column(
            "ward_id",
            sa.Uuid(),
            sa.ForeignKey("user_wards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("command_id", sa.String(200), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column(
            "period_id",
            sa.Uuid(),
            sa.ForeignKey("study_observation_quiet_periods.id", ondelete="CASCADE"),
        ),
        sa.Column("ward_version", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("help_offers", sa.Column("closed_reason", sa.String(40)))


def downgrade():
    op.drop_column("help_offers", "closed_reason")
    op.drop_table("study_observation_quiet_commands")
    op.drop_table("study_observation_quiet_periods")
