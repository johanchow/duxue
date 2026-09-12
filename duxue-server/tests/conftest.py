from __future__ import annotations

import os
from unittest.mock import patch
import pytest

# The developer's .env may point to Grafana Cloud. Tests must never create
# exporter threads or make an external telemetry request.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.ai_runtime.model_gateway import ModelGatewayError


@pytest.fixture(autouse=True)
def guard_external_ai_gateway():
    """Ensure no test inadvertently makes real external LLM/VLM calls."""
    with patch(
        "app.ai_runtime.model_gateway.QwenAgentModelGateway.generate",
        side_effect=ModelGatewayError("external_network_disabled_in_tests"),
    ):
        yield


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(db_engine):
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
