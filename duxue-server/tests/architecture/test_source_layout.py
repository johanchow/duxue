"""Structural guardrails for the server modular-monolith layout."""

from __future__ import annotations

import importlib
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = SERVER_ROOT / "app"


def test_production_code_has_one_app_root():
    assert SOURCE_ROOT.is_dir()
    assert not (SERVER_ROOT / "src").exists()
    assert not (SERVER_ROOT / "infrastructure").exists()


def test_layer_and_context_namespaces_exist():
    for name in ("bootstrap", "api", "application", "contexts", "infrastructure", "workers"):
        assert (SOURCE_ROOT / name).is_dir()
    for context in (
        "identity",
        "device_ingestion",
        "planning",
        "study",
        "behavior_analysis",
        "evaluation",
        "memory",
        "companion",
    ):
        assert (SOURCE_ROOT / "contexts" / context / "domain").is_dir()


def test_bootstrap_uses_the_api_assembly_boundary():
    bootstrap = importlib.import_module("app.bootstrap.app")
    api_router = importlib.import_module("app.api.router")
    assert bootstrap.app.router.routes
    assert api_router.router.routes


def test_companion_coordinator_is_an_application_process_manager():
    module = importlib.import_module("app.application.process_managers.companion_coordinator")
    assert hasattr(module, "CompanionCoordinator")
    assert "application/process_managers" in module.__file__.replace("\\", "/")
