"""Add gateway capture identity and immutable upload reservations.

Revision ID: 20261101_31
Revises: 20261030_30
"""

import sqlalchemy as sa
from alembic import op

revision = "20261101_31"
down_revision = "20261030_30"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table, columns in {
        "devices": [
            sa.Column("gateway_id", sa.String(64)),
            sa.Column("camera_id", sa.String(64)),
            sa.Column(
                "assignment_revision", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column(
                "gateway_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "gateway_erased",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        ],
        "frames": [
            sa.Column("gateway_id", sa.String(64)),
            sa.Column("gateway_frame_id", sa.Uuid(as_uuid=False)),
            sa.Column("sha256", sa.String(64)),
            sa.Column("size_bytes", sa.Integer()),
        ],
    }.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    for table, name, columns in [
        ("devices", "uq_device_gateway_camera", ["gateway_id", "camera_id"]),
        ("frames", "uq_frame_gateway_identity", ["gateway_id", "gateway_frame_id"]),
    ]:
        if name not in {
            c["name"] for c in sa.inspect(bind).get_unique_constraints(table)
        }:
            with op.batch_alter_table(table) as batch:
                batch.create_unique_constraint(name, columns)
    if not sa.inspect(bind).has_table("gateway_upload_reservations"):
        op.create_table(
            "gateway_upload_reservations",
            sa.Column("gateway_id", sa.String(64), primary_key=True),
            sa.Column("frame_id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column(
                "device_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("devices.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("oss_key", sa.String(500), nullable=False, unique=True),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "purging", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
        op.create_index(
            "ix_gateway_upload_reservations_device_id",
            "gateway_upload_reservations",
            ["device_id"],
        )
        op.create_index(
            "ix_gateway_upload_reservations_created_at",
            "gateway_upload_reservations",
            ["created_at"],
        )
    if not sa.inspect(bind).has_table("gateway_health"):
        op.create_table(
            "gateway_health",
            sa.Column("gateway_id", sa.String(64), primary_key=True),
            sa.Column("boot_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("retired_boots", sa.JSON(), nullable=False),
            sa.Column("cameras", sa.JSON(), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not sa.inspect(bind).has_table("capture_audit"):
        op.create_table(
            "capture_audit",
            sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column(
                "ward_id",
                sa.Uuid(as_uuid=False),
                sa.ForeignKey("user_wards.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("aggregate_id", sa.String(64), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_capture_audit_ward_id", "capture_audit", ["ward_id"])


def downgrade():
    for table in ("capture_audit", "gateway_health", "gateway_upload_reservations"):
        op.drop_table(table)
    for table, name, columns in [
        (
            "frames",
            "uq_frame_gateway_identity",
            ["size_bytes", "sha256", "gateway_frame_id", "gateway_id"],
        ),
        (
            "devices",
            "uq_device_gateway_camera",
            [
                "gateway_erased",
                "gateway_enabled",
                "assignment_revision",
                "camera_id",
                "gateway_id",
            ],
        ),
    ]:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="unique")
            for column in columns:
                batch.drop_column(column)
