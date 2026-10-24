"""Replace Guardian passwords with one-time email challenges.

Revision ID: 20261024_28
Revises: 20261023_27
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_28"
down_revision = "20261023_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # The historical empty-schema rebuild can already create current ORM tables.
    if not inspector.has_table("email_auth_challenges"):
        op.create_table(
            "email_auth_challenges",
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("request_ip_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_email_auth_challenges_email", "email_auth_challenges", ["email"])
        op.create_index("ix_email_auth_challenges_request_ip_hash", "email_auth_challenges", ["request_ip_hash"])
    if not inspector.has_table("email_auth_failures"):
        op.create_table(
            "email_auth_failures",
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("request_ip_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_email_auth_failures_email", "email_auth_failures", ["email"])
        op.create_index("ix_email_auth_failures_request_ip_hash", "email_auth_failures", ["request_ip_hash"])
    if inspector.has_table("user_guardians") and "password_hash" in {column["name"] for column in inspector.get_columns("user_guardians")}:
        with op.batch_alter_table("user_guardians") as batch:
            batch.drop_column("password_hash")


def downgrade() -> None:
    raise RuntimeError("Password hashes cannot be recovered after this migration")
