"""Real PostgreSQL migrations and concurrent idempotency, isolated from .env DBs.

CI sets TEST_GATEWAY_DATABASE_URL to a disposable duxue_gateway_test_* database.
Locally, an installed PostgreSQL creates a temporary cluster instead of Docker.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.application.commands.gateway_ingestion import GatewayCommands, GatewayPrincipal
from app.contexts.ingestion.domain.gateway import Evidence
from app.infrastructure.persistence.gateway_repository import SqlCaptureRepository
from app.infrastructure.persistence.models import (
    Device,
    Frame,
    GatewayUploadReservation,
    OutboxEvent,
    User,
    Ward,
)


@pytest.fixture(scope="module")
def postgres_url(tmp_path_factory):
    configured = os.getenv("TEST_GATEWAY_DATABASE_URL")
    if configured:
        if not (make_url(configured).database or "").startswith("duxue_gateway_test_"):
            pytest.fail(
                "TEST_GATEWAY_DATABASE_URL must name a disposable duxue_gateway_test_* database"
            )
        yield configured
        return
    postgres = shutil.which("postgres")
    initdb = shutil.which("initdb") or (
        "/opt/homebrew/opt/libpq/bin/initdb"
        if Path("/opt/homebrew/opt/libpq/bin/initdb").exists()
        else None
    )
    pg_ctl = shutil.which("pg_ctl") or (
        str(Path(postgres).resolve().parent / "pg_ctl") if postgres else None
    )
    if not postgres or not initdb or not pg_ctl:
        pytest.skip("PostgreSQL tools or disposable TEST_GATEWAY_DATABASE_URL required")
    root = tmp_path_factory.mktemp("gateway-postgres")
    data = root / "data"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    subprocess.run(
        [
            initdb,
            "-D",
            str(data),
            "--auth=trust",
            "-U",
            "gateway_test",
            "--no-locale",
            "-E",
            "UTF8",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -c unix_socket_directories=",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        yield f"postgresql+psycopg://gateway_test@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True,
            capture_output=True,
        )


@pytest.fixture(scope="module")
def migrated_engine(postgres_url):
    env = {
        **os.environ,
        "DATABASE_URL": postgres_url,
        "SECRET_KEY": "gateway-test-only",
        "JWT_SECRET_KEY": "gateway-test-only",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "VLM_API_KEY": "test-only",
        "STORAGE_BACKEND": "local",
        "OTEL_SDK_DISABLED": "true",
        "GATEWAY_CREDENTIALS_JSON": "[]",
        "AUTO_CREATE_SCHEMA": "false",
        "ENV_FILE": "/dev/null",
    }
    server = Path(__file__).resolve().parents[2]
    # Exercise the incremental migration against the preceding production shape.
    # Historical migration 02 cannot rebuild a populated FK graph on PostgreSQL;
    # testing that unrelated pre-UUID history is not part of this gateway change.
    from app.infrastructure.persistence.database import Base

    initial = create_engine(postgres_url)
    Base.metadata.create_all(initial)
    initial.dispose()
    for action, revision in (
        ("stamp", "head"),
        ("downgrade", "20261030_30"),
        ("upgrade", "head"),
    ):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", action, revision],
            cwd=server,
            env=env,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            pytest.fail(result.stderr.decode()[-7000:])
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


class MemoryStorage:
    def __init__(self, image):
        self.image = image

    def upload_url(self, key, base_url, content_type, *, immutable=False):
        assert immutable
        return (
            "https://unused.invalid",
            int(datetime.now(timezone.utc).timestamp()) + 300,
            {},
        )

    def read_limited(self, key, maximum):
        return self.image


def test_postgres_migration_and_concurrent_frame_commit(migrated_engine):
    engine = migrated_engine
    assert "uq_device_gateway_camera" in {
        c["name"] for c in inspect(engine).get_unique_constraints("devices")
    }
    assert "uq_frame_gateway_identity" in {
        c["name"] for c in inspect(engine).get_unique_constraints("frames")
    }
    factory = sessionmaker(bind=engine)
    ward_id = str(uuid4())
    actor = GatewayPrincipal("pg-" + uuid4().hex[:12], frozenset({ward_id}))
    with factory() as db:
        db.add(User(id=ward_id, type="ward"))
        db.flush()
        db.add(Ward(id=ward_id, display_name="Postgres test", grade_stage="primary"))
        db.commit()
    image = b"\xff\xd8jpeg\xff\xd9"
    storage = MemoryStorage(image)

    def register(_):
        with factory() as db:
            return GatewayCommands(SqlCaptureRepository(db), storage).register(
                actor, "camera-01", ward_id
            )[0]

    with ThreadPoolExecutor(max_workers=6) as pool:
        registrations = list(pool.map(register, range(6)))
    assert len({r.device_id for r in registrations}) == 1
    evidence = Evidence(
        actor.gateway_id,
        str(uuid4()),
        "camera-01",
        ward_id,
        1,
        datetime.now(timezone.utc),
        hashlib.sha256(image).hexdigest(),
        len(image),
    )
    with factory() as db:
        GatewayCommands(SqlCaptureRepository(db), storage).reserve(
            actor, evidence, datetime.now(timezone.utc), ""
        )

    def commit(_):
        with factory() as db:
            return GatewayCommands(SqlCaptureRepository(db), storage).accept(
                actor, evidence, evidence.object_key(), datetime.now(timezone.utc)
            )[0]

    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(commit, range(6)))
    assert len({f.id for f in frames}) == 1
    with factory() as db:
        assert db.query(Frame).filter_by(ward_id=ward_id).count() == 1
        assert (
            db.query(OutboxEvent)
            .filter_by(aggregate_id=frames[0].id, event_type="LearningFactRecorded.v1")
            .count()
            == 1
        )
        assert db.query(Device).filter_by(gateway_id=actor.gateway_id).count() == 1


def test_postgres_frame_and_fact_rollback_together(migrated_engine, monkeypatch):
    factory = sessionmaker(bind=migrated_engine)
    ward_id = str(uuid4())
    gateway = "rollback-" + uuid4().hex[:12]
    actor = GatewayPrincipal(gateway, frozenset({ward_id}))
    image = b"\xff\xd8jpeg\xff\xd9"
    storage = MemoryStorage(image)
    with factory() as db:
        db.add(User(id=ward_id, type="ward"))
        db.flush()
        db.add(Ward(id=ward_id, display_name="rollback", grade_stage="primary"))
        db.commit()
        service = GatewayCommands(SqlCaptureRepository(db), storage)
        service.register(actor, "camera", ward_id)
        evidence = Evidence(
            gateway,
            str(uuid4()),
            "camera",
            ward_id,
            1,
            datetime.now(timezone.utc),
            hashlib.sha256(image).hexdigest(),
            len(image),
        )
        service.reserve(actor, evidence, datetime.now(timezone.utc), "")

        def fail(*args, **kwargs):
            raise RuntimeError("injected outbox failure")

        monkeypatch.setattr(
            "app.infrastructure.persistence.gateway_repository.publish_learning_fact",
            fail,
        )
        with pytest.raises(RuntimeError, match="injected"):
            service.accept(
                actor, evidence, evidence.object_key(), datetime.now(timezone.utc)
            )
    with factory() as db:
        assert db.query(Frame).filter_by(ward_id=ward_id).count() == 0
        assert (
            db.query(GatewayUploadReservation).filter_by(gateway_id=gateway).count()
            == 1
        )
