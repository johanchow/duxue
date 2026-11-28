"""Give the objective evening report and its immutable versions their domain names."""

from alembic import op
from sqlalchemy import inspect

revision = "20261128_48"
down_revision = "20261128_47"
branch_labels = depends_on = None


def rename(source, target):
    if inspect(op.get_bind()).has_table(source + "_reports"):
        op.rename_table(source + "_reports", target + "_reports")
        op.rename_table(source + "_report_versions", target + "_report_versions")
        op.execute(
            f"ALTER INDEX IF EXISTS ix_{source}_reports_ward_id RENAME TO ix_{target}_reports_ward_id"
        )


def upgrade():
    rename("reflection", "evening")


def downgrade():
    rename("evening", "reflection")
