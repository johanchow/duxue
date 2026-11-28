"""Keep the source conversation as an indexed cross-domain ID."""

import sqlalchemy as sa
from alembic import op

revision = "20261128_46"
down_revision = "20261128_45"
branch_labels = depends_on = None


def upgrade():
    for key in sa.inspect(op.get_bind()).get_foreign_keys("creative_works"):
        if (
            key["constrained_columns"] == ["source_thread_id"]
            and key["referred_table"] == "conversation_threads"
        ):
            op.drop_constraint(key["name"], "creative_works", type_="foreignkey")


def downgrade():
    op.create_foreign_key(
        "creative_works_source_thread_id_fkey",
        "creative_works",
        "conversation_threads",
        ["source_thread_id"],
        ["id"],
    )
