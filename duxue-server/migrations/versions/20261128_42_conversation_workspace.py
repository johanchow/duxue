"""Guardian ownership and durable conversation turns."""

from alembic import op
import sqlalchemy as sa

revision = "20261128_42"
down_revision = "20261127_41"
branch_labels = depends_on = None


def upgrade():
    schema = sa.inspect(op.get_bind())
    columns = {c["name"] for c in schema.get_columns("conversation_threads")}
    op.alter_column("conversation_threads", "ward_id", nullable=True)
    if "guardian_id" not in columns:
        op.add_column(
            "conversation_threads",
            sa.Column("guardian_id", sa.Uuid(), sa.ForeignKey("user_guardians.id")),
        )
        op.create_index(
            "ix_conversation_threads_guardian_id",
            "conversation_threads",
            ["guardian_id"],
        )
    for column in (
        sa.Column("title", sa.String(80), nullable=False, server_default="新对话"),
        sa.Column("clear_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    ):
        if column.name not in columns:
            op.add_column("conversation_threads", column)
    if schema.has_table("guardian_conversation_turns"):
        return
    op.create_table(
        "guardian_conversation_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_threads.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("command_id", sa.String(128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("reply", sa.JSON(), nullable=False),
        sa.Column("continuation", sa.JSON(), nullable=False),
        sa.UniqueConstraint("thread_id", "command_id"),
        sa.UniqueConstraint("thread_id", "position"),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM conversation_threads WHERE guardian_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Export adult conversations before downgrading this schema")
    op.drop_table("guardian_conversation_turns")
    for column in ("deleted", "clear_version", "title", "guardian_id"):
        op.drop_column("conversation_threads", column)
    op.alter_column("conversation_threads", "ward_id", nullable=False)
