"""Converge task/session and memory tables on the target model.

This migration is intentionally valid only for an empty development database.
It replaces the pre-convergence task-plan tables; deployment must run the
application-level empty-database preflight before invoking this revision.
"""

from alembic import op
from sqlalchemy import inspect

from app.database import Base
from app import models  # noqa: F401 - registers all target metadata


revision = "20260830_08"
down_revision = "20260825_07"
branch_labels = None
depends_on = None


_OLD_TABLES_CHILD_FIRST = (
    "focus_kits", "self_reviews", "study_messages", "study_sessions",
    "plan_items", "daily_plans", "assignments", "ward_invites",
    "ward_credentials", "reports", "behavior_segments", "frame_predictions",
    "frames", "analysis_batches", "devices", "guardian_ward_relations",
    "user_wards", "behavior_label_configs", "analysis_profiles", "refresh_tokens",
    "user_guardians", "users",
)


def upgrade() -> None:
    bind = op.get_bind()
    # The deploy preflight establishes the database is empty.  Drop in explicit
    # dependency order rather than relying on database-level CASCADE.
    tables = set(inspect(bind).get_table_names())
    for name in _OLD_TABLES_CHILD_FIRST:
        if name in tables:
            op.drop_table(name)
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise RuntimeError("The empty-database convergence migration is intentionally not reversible")
