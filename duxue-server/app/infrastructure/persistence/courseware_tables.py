"""Relational storage for adult courseware and its immutable version payloads."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

from app.infrastructure.persistence.database import Base

coursewares = Table(
    "mentor_coursewares",
    Base.metadata,
    Column("courseware_id", Uuid, primary_key=True),
    Column("guardian_id", Uuid, nullable=False),
    Column("command_id", String(128), nullable=False),
    Column("state_revision", Integer, nullable=False),
    Column("retention_status", String(16), nullable=False),
    Column("title", String(80), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("payload", JSON, nullable=False),
    Column("photos", JSON, nullable=False),
    UniqueConstraint("guardian_id", "command_id"),
)
versions = Table(
    "mentor_courseware_versions",
    Base.metadata,
    Column(
        "courseware_id",
        Uuid,
        ForeignKey("mentor_coursewares.courseware_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("version_no", Integer, primary_key=True),
    Column("payload", JSON, nullable=False),
)
Index(
    "ix_courseware_saved",
    coursewares.c.guardian_id,
    coursewares.c.retention_status,
    coursewares.c.updated_at,
    coursewares.c.courseware_id,
)
Index("ix_courseware_expiry", coursewares.c.expires_at)
