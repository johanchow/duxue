"""Shared root, immutable versions and command receipts for educational artifacts."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.types import TypeDecorator

from app.infrastructure.persistence.database import Base


class ArtifactId(TypeDecorator):
    impl = Uuid(as_uuid=False)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None


def utcnow():
    return datetime.now(timezone.utc)


artifacts = Table(
    "edu_artifacts",
    Base.metadata,
    Column("artifact_id", ArtifactId(), primary_key=True, default=lambda: str(uuid4())),
    Column("owner_id", ArtifactId(), nullable=False),
    Column("artifact_type", String(32), nullable=False),
    Column("source_thread_id", ArtifactId(), index=True),
    Column("command_id", String(128)),
    Column("state_revision", Integer, nullable=False, default=1),
    Column("retention_status", String(16), nullable=False, default="temporary"),
    Column("title", String(80), nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    ),
    Column("expires_at", DateTime(timezone=True)),
    Column("payload", JSON, nullable=False, default=dict),
    Column("photos", JSON, nullable=False, default=list),
    Column("branch", JSON, nullable=False, default=lambda: [1]),
    Column("cursor", Integer, nullable=False, default=0),
    UniqueConstraint("owner_id", "command_id", name="uq_artifact_create_command"),
)
versions = Table(
    "edu_artifact_versions",
    Base.metadata,
    Column(
        "artifact_id",
        ArtifactId(),
        ForeignKey(artifacts.c.artifact_id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("version_no", Integer, primary_key=True),
    Column("payload", JSON, nullable=False),
)
receipts = Table(
    "edu_artifact_commands",
    Base.metadata,
    Column(
        "artifact_id",
        ArtifactId(),
        ForeignKey(artifacts.c.artifact_id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("command_id", String(128), primary_key=True),
    Column("digest", String(64), nullable=False),
    Column("result", JSON, nullable=False),
)
Index(
    "ix_edu_artifact_library",
    artifacts.c.owner_id,
    artifacts.c.retention_status,
    artifacts.c.updated_at,
    artifacts.c.artifact_id,
)
Index("ix_edu_artifact_expiry", artifacts.c.expires_at)
