"""Remove the legacy tenant boundary and add ward grade stages.

Revision ID: 20260823_04
Revises: 20260822_03
"""
from alembic import op
import sqlalchemy as sa


revision = "20260823_04"
down_revision = "20260822_03"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "users", "analysis_profiles", "user_wards", "guardian_ward_relations",
    "behavior_label_configs", "devices", "analysis_batches", "frames",
    "frame_predictions", "behavior_segments", "reports", "ward_invites",
    "assignments", "daily_plans", "study_sessions", "self_reviews", "focus_kits",
)


def _drop_tenant_column(table: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "tenant_id" not in columns:
        return

    if bind.dialect.name != "sqlite":
        for foreign_key in inspector.get_foreign_keys(table):
            if "tenant_id" in foreign_key["constrained_columns"]:
                op.drop_constraint(foreign_key["name"], table, type_="foreignkey")
        for constraint in inspector.get_unique_constraints(table):
            if "tenant_id" in constraint["column_names"]:
                op.drop_constraint(constraint["name"], table, type_="unique")
        for index in inspector.get_indexes(table):
            if "tenant_id" in index["column_names"]:
                op.drop_index(index["name"], table_name=table)
        op.drop_column(table, "tenant_id")
        return

    # Batch mode makes this portable to SQLite (used by the test suite).
    with op.batch_alter_table(table, recreate="always") as batch:
        for index in inspector.get_indexes(table):
            if "tenant_id" in index["column_names"] and index.get("name"):
                batch.drop_index(index["name"])
        for constraint in inspector.get_unique_constraints(table):
            if "tenant_id" in constraint["column_names"] and constraint.get("name"):
                batch.drop_constraint(constraint["name"], type_="unique")
        for foreign_key in inspector.get_foreign_keys(table):
            if "tenant_id" in foreign_key["constrained_columns"] and foreign_key.get("name"):
                batch.drop_constraint(foreign_key["name"], type_="foreignkey")
        batch.drop_column("tenant_id")


def upgrade() -> None:
    for table in TENANT_TABLES:
        _drop_tenant_column(table)

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "grade_stage" not in {column["name"] for column in inspector.get_columns("user_wards")}:
        column = sa.Column("grade_stage", sa.String(20), nullable=False, server_default="primary")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("user_wards", recreate="always") as batch:
                batch.add_column(column)
        else:
            op.add_column("user_wards", column)
    if inspector.has_table("tenants"):
        op.drop_table("tenants")


def downgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("plan", sa.String(30), nullable=False, server_default="self_hosted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in TENANT_TABLES:
        bind = op.get_bind()
        if sa.inspect(bind).has_table(table):
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.add_column(sa.Column("tenant_id", sa.String(36), nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("user_wards", recreate="always") as batch:
            batch.drop_column("grade_stage")
    else:
        op.drop_column("user_wards", "grade_stage")
