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


def test_context_routers_are_aggregated_without_duplicate_operations():
    api_root = SOURCE_ROOT / "api" / "v1"
    module_names = (
        "system",
        "identity",
        "device_ingestion",
        "planning",
        "study",
        "evaluation",
        "memory",
        "companion",
        "behavior",
    )
    assert not (api_root / "routes.py").exists()

    operations: list[tuple[str, str]] = []
    for name in module_names:
        module = importlib.import_module(f"app.api.v1.{name}")
        assert hasattr(module, "router")
        for route in module.router.routes:
            for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
                operations.append((route.path, method))

    assert len(operations) == len(set(operations))
    assert "@router." not in (SOURCE_ROOT / "api" / "router.py").read_text(encoding="utf-8")


def test_companion_coordinator_is_an_application_process_manager():
    module = importlib.import_module("app.application.process_managers.companion_coordinator")
    assert hasattr(module, "CompanionCoordinator")
    assert "application/process_managers" in module.__file__.replace("\\", "/")
