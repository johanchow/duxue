"""Track the creator and email invitations for shared Ward profiles."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_38"
down_revision = "20261117_37"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_wards") as table:
        table.add_column(sa.Column("owner_guardian_id", sa.Uuid()))
        table.create_foreign_key(
            "fk_ward_owner_guardian", "user_guardians", ["owner_guardian_id"], ["id"]
        )
    op.execute("""
        UPDATE user_wards SET owner_guardian_id = (
            SELECT guardian_id FROM guardian_ward_relations
            WHERE ward_id = user_wards.id
        ) WHERE 1 = (
            SELECT count(*) FROM guardian_ward_relations WHERE ward_id = user_wards.id
        )
    """)
    op.create_table(
        "guardian_ward_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ward_id", sa.Uuid(), sa.ForeignKey("user_wards.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_guardian_ward_invites_ward_id", "guardian_ward_invites", ["ward_id"]
    )
    op.create_index(
        "ix_guardian_ward_invites_email", "guardian_ward_invites", ["email"]
    )


def downgrade():
    op.drop_table("guardian_ward_invites")
    with op.batch_alter_table("user_wards") as table:
        table.drop_constraint("fk_ward_owner_guardian", type_="foreignkey")
        table.drop_column("owner_guardian_id")
