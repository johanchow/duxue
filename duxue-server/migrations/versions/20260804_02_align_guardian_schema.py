"""Align an existing pre-Alembic database with the simplified guardian schema.

Revision ID: 20260804_02
Revises: 20260804_01
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260804_02"
down_revision = "20260804_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Existing databases may still contain the old role vocabulary. Convert the
    # data before adding the new invariant.
    if inspector.has_table("user_guardians"):
        bind.execute(sa.text("UPDATE user_guardians SET role = 'admin' WHERE role = 'owner'"))
        bind.execute(sa.text("UPDATE user_guardians SET role = 'guardian' WHERE role IN ('teacher', 'parent')"))
        checks = {item["name"] for item in inspector.get_check_constraints("user_guardians")}
        if "ck_guardian_role" not in checks:
            op.create_check_constraint("ck_guardian_role", "user_guardians", "role IN ('admin', 'guardian')")
        op.alter_column("user_guardians", "role", server_default="guardian")

    if inspector.has_table("user_wards"):
        columns = {item["name"] for item in inspector.get_columns("user_wards")}
        if "birth_year" in columns:
            op.drop_column("user_wards", "birth_year")

    if inspector.has_table("guardian_ward_relations"):
        columns = {item["name"] for item in inspector.get_columns("guardian_ward_relations")}
        if "relation_type" in columns:
            op.drop_column("guardian_ward_relations", "relation_type")


def downgrade() -> None:
    op.add_column("user_wards", sa.Column("birth_year", sa.Integer(), nullable=True))
    op.add_column("guardian_ward_relations", sa.Column("relation_type", sa.String(30), nullable=True, server_default="guardian"))
    op.drop_constraint("ck_guardian_role", "user_guardians", type_="check")
    op.alter_column("user_guardians", "role", server_default="parent")
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE user_guardians SET role = 'owner' WHERE role = 'admin'"))
    bind.execute(sa.text("UPDATE user_guardians SET role = 'parent' WHERE role = 'guardian'"))
