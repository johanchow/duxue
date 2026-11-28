"""Ward storybooks, immutable versions and command receipts."""

from alembic import op
import sqlalchemy as sa

revision = "20261128_43"
down_revision = "20261128_42"
branch_labels = depends_on = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("creative_works"):
        return
    op.create_table(
        "creative_works",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ward_id",
            sa.Uuid(),
            sa.ForeignKey("user_wards.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_thread_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_threads.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("branch", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "creative_work_versions",
        sa.Column(
            "work_id", sa.Uuid(), sa.ForeignKey("creative_works.id"), primary_key=True
        ),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("pages", sa.JSON(), nullable=False),
    )
    op.create_table(
        "creative_work_commands",
        sa.Column(
            "work_id", sa.Uuid(), sa.ForeignKey("creative_works.id"), primary_key=True
        ),
        sa.Column("command_id", sa.String(128), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade():
    for table in ("creative_work_commands", "creative_work_versions", "creative_works"):
        op.drop_table(table)
