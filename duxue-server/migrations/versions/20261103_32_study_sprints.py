"""Independent, Ward-authorized focus sprints. Preserve all existing task/history rows."""

from alembic import op
import sqlalchemy as sa

revision = "20261103_32"
down_revision = "20261101_31"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("duration_kind", sa.String(30), nullable=True))
    op.add_column("tasks", sa.Column("duration_source", sa.String(30), nullable=True))
    op.create_table(
        "study_sprints",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("user_wards.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id", sa.Uuid(as_uuid=False), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column(
            "study_session_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("study_sessions.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("target_seconds", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("active_since", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("end_reason", sa.String(30)),
        sa.Column("intervals", sa.JSON(), nullable=False),
        sa.Column("notice_claimed", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("target_seconds > 0", name="ck_sprint_positive_duration"),
        sa.CheckConstraint(
            "elapsed_seconds >= 0 AND elapsed_seconds <= target_seconds",
            name="ck_sprint_elapsed",
        ),
        sa.CheckConstraint(
            "status IN ('ready','active','paused','elapsed','ended','cancelled')",
            name="ck_sprint_status",
        ),
    )
    op.create_index("ix_study_sprints_ward_id", "study_sprints", ["ward_id"])
    op.create_index(
        "uq_sprint_live_ward",
        "study_sprints",
        ["ward_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active','paused')"),
        sqlite_where=sa.text("status IN ('active','paused')"),
    )
    op.create_table(
        "study_sprint_commands",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("user_wards.id"),
            nullable=False,
        ),
        sa.Column("command_id", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.UniqueConstraint("ward_id", "command_id", name="uq_sprint_command"),
    )
    op.create_index(
        "ix_study_sprint_commands_ward_id", "study_sprint_commands", ["ward_id"]
    )
    # Old review cards must be re-reviewed under the new optional-time contract.
    op.execute(
        "UPDATE plan_drafts SET status = 'superseded', version = version + 1 WHERE status = 'active'"
    )


def downgrade():
    op.drop_table("study_sprint_commands")
    op.drop_table("study_sprints")
    op.drop_column("tasks", "duration_source")
    op.drop_column("tasks", "duration_kind")
