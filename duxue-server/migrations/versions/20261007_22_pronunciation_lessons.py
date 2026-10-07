"""Add the read-only pronunciation lesson projection."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261007_22"
down_revision = "20260926_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "pronunciation_lessons" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "pronunciation_lessons",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("ward_id", sa.Uuid(as_uuid=False), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("thread_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("turn_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("introduction", sa.Text(), nullable=False),
        sa.Column("reading_guide", sa.Text(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("speech_ref", sa.String(length=64), nullable=False),
        sa.Column("supported_rates", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "turn_id", "attempt", name="uq_pronunciation_lesson_run_turn_attempt"),
    )
    op.create_index("ix_pronunciation_lessons_ward_id", "pronunciation_lessons", ["ward_id"])
    op.create_index("ix_pronunciation_lessons_thread_id", "pronunciation_lessons", ["thread_id"])
    op.create_index("ix_pronunciation_lessons_run_id", "pronunciation_lessons", ["run_id"])


def downgrade() -> None:
    if "pronunciation_lessons" not in inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_pronunciation_lessons_run_id", table_name="pronunciation_lessons")
    op.drop_index("ix_pronunciation_lessons_thread_id", table_name="pronunciation_lessons")
    op.drop_index("ix_pronunciation_lessons_ward_id", table_name="pronunciation_lessons")
    op.drop_table("pronunciation_lessons")
