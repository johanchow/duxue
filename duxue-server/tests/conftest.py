from __future__ import annotations

import os
from unittest.mock import patch
import pytest

# The developer's .env may point to Grafana Cloud. Tests must never create
# exporter threads or make an external telemetry request.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import json
from pathlib import Path
from functools import lru_cache
from app.agent_specs import definitions as _definitions
from app.agent_specs.catalog import AgentCatalog, AgentSpec

_TEST_ROOT = Path(__file__).parent / "fixtures/agent_specs"
_TEST_SNAPSHOT = Path(__file__).parent / "fixtures/admin-release.json"
os.environ["AGENT_CONFIG_SOURCE"] = "snapshot"
os.environ["AGENT_CONFIG_SNAPSHOT"] = str(_TEST_SNAPSHOT)
_definitions.ROOT = _TEST_ROOT


@lru_cache(maxsize=1)
def _load_test_definitions() -> _definitions.DefinitionCatalog:
    catalog = _definitions.DefinitionCatalog(_TEST_ROOT)
    snapshot = json.loads(_TEST_SNAPSHOT.read_text(encoding="utf-8"))
    specs = {
        Path(name).stem: AgentSpec.model_validate({"version": "v1", **doc})
        for name, doc in sorted(snapshot["bundle"]["files"].items())
        if name.startswith("workflows/") and name.endswith(".json")
    }
    with _definitions.use_definitions(catalog):
        catalog.workflow_catalog = AgentCatalog(specs, _TEST_ROOT)
    return catalog


_definitions.base_definitions = _load_test_definitions

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.persistence.database import Base, get_db
from app.bootstrap.app import app
from app.infrastructure.ai.errors import ModelGatewayError


@pytest.fixture(autouse=True)
def guard_external_ai_gateway():
    """Ensure no test inadvertently makes real external LLM/VLM calls."""
    with patch(
        "app.infrastructure.ai.components.invoke_json_component",
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
