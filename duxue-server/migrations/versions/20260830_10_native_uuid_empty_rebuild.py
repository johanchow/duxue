"""Rebuild the authorized empty target schema with PostgreSQL native UUID IDs."""

from alembic import op
from sqlalchemy import inspect

from app.infrastructure.persistence.database import Base
import app.infrastructure.persistence.models  # noqa: F401 - registers target metadata


revision = "20260830_10"
down_revision = "20260830_09"
branch_labels = None
depends_on = None


_TABLES_CHILD_FIRST = (
    "derived_signal_events", "episodic_memory_events", "tutoring_messages",
    "tutoring_sessions", "study_session_intervals", "behavior_segments", "frame_predictions",
    "frames", "outbox_events",
    "learning_events", "long_term_profiles", "derived_signals", "episodic_memories",
    "focus_kits", "self_reviews", "study_sessions", "tasks", "daily_schedules",
    "ward_invites", "ward_credentials", "reports", "analysis_batches", "devices",
    "guardian_ward_relations", "user_wards", "behavior_label_configs",
    "analysis_profiles", "refresh_tokens", "user_guardians", "users",
)


def upgrade() -> None:
    # This revision is only for the explicitly authorized, empty target DB.
    # Tables are removed in dependency order; no DROP ... CASCADE is used.
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in _TABLES_CHILD_FIRST:
        if table in existing:
            op.drop_table(table)
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise RuntimeError("The authorized empty-database UUID rebuild is not reversible")
