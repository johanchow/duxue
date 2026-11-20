"""Tests for pre-publish Judge contract validation (static compile gate + live/fake probe)."""

from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import read_snapshot
from app.agent_specs.judge_preflight import probe_judge_contracts
from app.api.v1.agent_admin import router as agent_admin_router
from scripts.upgrade_math_bundle import upgrade as enable_math


def test_compile_bundle_rejects_math_enabled_judge_missing_math_consistent_in_prompt():
    """Catches R12-style drift where [math.v1] remains but math_consistent is removed from prompt."""
    upgraded = enable_math(read_snapshot(), enable=True)
    bad = copy.deepcopy(upgraded["bundle"])
    tpl = bad["files"]["gates/tutoring.leak-judge.json"]["prompt"]["template"]
    bad["files"]["gates/tutoring.leak-judge.json"]["prompt"]["template"] = tpl.replace(
        "math_consistent", "removed_field"
    )
    with pytest.raises(ValueError, match="math_consistent"):
        compile_bundle(bad)


def test_probe_judge_contracts_passes_when_both_text_and_math_judges_valid():
    class GoodJudge:
        def leaks(self, *, text, task_title, problem_summary, images=None):
            return {"leaks": False, "reason": None, "answer_protected": True}

        def check_math(self, *, text, context, images):
            return True

    compiled = compile_bundle(enable_math(read_snapshot(), enable=True)["bundle"])
    assert probe_judge_contracts(compiled, judge=GoodJudge()) == []


def test_probe_judge_contracts_catches_missing_math_consistent_and_missing_text_fields():
    class R12BrokenJudge:
        def leaks(self, *, text, task_title, problem_summary, images=None):
            return {"leaks": False, "reason": None}  # missing answer_protected

        def check_math(self, *, text, context, images):
            return None  # R12 returned JSON without math_consistent

    compiled = compile_bundle(enable_math(read_snapshot(), enable=True)["bundle"])
    errors = probe_judge_contracts(compiled, judge=R12BrokenJudge())
    assert any("answer_protected" in err for err in errors)
    assert any("math_consistent" in err for err in errors)


def test_validate_endpoint_supports_optional_probe_judges(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_INTERNAL_TOKEN", "test-secret")
    monkeypatch.setattr(
        "app.agent_specs.judge_preflight.probe_judge_contracts",
        lambda snapshot: ["math_consistency probe failed: missing boolean 'math_consistent' output"],
    )
    bundle = enable_math(read_snapshot(), enable=True)["bundle"]
    test_app = FastAPI()
    test_app.include_router(agent_admin_router)
    client = TestClient(test_app)

    # Default probe_judges=False does not invoke probe
    resp_default = client.post(
        "/internal/agent-admin/validate",
        headers={"Authorization": "Bearer test-secret"},
        json={"bundle": bundle},
    )
    assert resp_default.status_code == 200
    assert resp_default.json()["valid"] is True

    # probe_judges=True surfaces probe errors in runtime_errors and runtime_ready=False
    resp_probe = client.post(
        "/internal/agent-admin/validate",
        headers={"Authorization": "Bearer test-secret"},
        json={"bundle": bundle, "probe_judges": True},
    )
    assert resp_probe.status_code == 200
    data = resp_probe.json()
    assert data["valid"] is True
    assert data["runtime_ready"] is False
    assert any("math_consistent" in e for e in data["runtime_errors"])
