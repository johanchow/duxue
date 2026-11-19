import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.definitions import use_definitions
from app.agent_specs.execution_trace import Recorder
from app.application.workflows import guardian_mentor
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from scripts.upgrade_guardian_mentor_review import upgrade


@pytest.fixture(scope="module")
def staged():
    record = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    upgraded = upgrade(record)
    assert upgrade(upgraded)["digest"] == upgraded["digest"]
    return compile_bundle(upgraded["bundle"]).catalog


def _review(*items, coverage=True):
    return {
        "coverage_complete": coverage,
        "rows": [
            {
                "id": key,
                "status": status,
                "reason": "错误方向" if status == "wrong" else "",
            }
            for key, status in items
        ],
    }


@pytest.mark.parametrize("recheck", ["pass", "wrong", "transport_error"])
def test_guardian_repairs_only_failed_part_and_keeps_approved_text(
    staged, monkeypatch, recheck
):
    monkeypatch.setattr(guardian_mentor, "_solve_for_mentor", lambda **kwargs: None)
    calls = []

    def provider(*, spec, user, **kwargs):
        calls.append(spec.component_id)
        if spec.component_id == "tutoring.mentor-explain":
            return {
                "act": "explain",
                "content": "unused overview",
                "sections": [
                    {"id": "1", "content": "错误证明"},
                    {"id": "2", "content": "已审核的第二问"},
                ],
            }
        if spec.component_id == "tutoring.mentor-repair":
            text = str(user)
            assert "错误方向" in text
            return {"sections": [{"id": "1", "content": "修正证明"}]}
        if calls.count("tutoring.mentor-review") == 1:
            return _review(("1", "wrong"), ("2", "pass"))
        if recheck == "transport_error":
            raise ModelGatewayError("model_transport_error")
        return _review(("1", recheck))

    monkeypatch.setattr(components, "invoke_json_component", provider)
    trace = Recorder()
    with use_definitions(staged), trace.capture():
        response = guardian_mentor.explain_for_guardian(
            guardian_id=str(uuid4()),
            content="两问",
            attachment_keys=[],
            window=[],
            images=[],
            rows=[],
        )
    assert response["act"] == "explain"
    assert (
        "已审核的第二问" in response["content"]
        and "错误证明" not in response["content"]
    )
    assert ("修正证明" in response["content"]) == (recheck == "pass")
    assert ("部分小问" in response["content"]) == (recheck != "pass")
    assert [
        e["node_id"].split(".")[-1]
        for e in trace.events
        if e["kind"] in {"agent", "gate", "action"}
    ] == ["explain", "review", "repair", "recheck", "deliver"]


def test_mismatched_review_ids_never_release_unreviewed_content(staged, monkeypatch):
    monkeypatch.setattr(guardian_mentor, "_solve_for_mentor", lambda **kwargs: None)

    def provider(*, spec, **kwargs):
        if spec.component_id == "tutoring.mentor-explain":
            return {
                "act": "explain",
                "content": "候选文字",
                "sections": [
                    {"id": "1", "content": "第一问"},
                    {"id": "2", "content": "第二问"},
                ],
            }
        return _review(("1", "pass"), ("3", "pass"))

    monkeypatch.setattr(components, "invoke_json_component", provider)
    with use_definitions(staged):
        response = guardian_mentor.explain_for_guardian(
            guardian_id=str(uuid4()),
            content="两问",
            attachment_keys=[],
            window=[],
            images=[],
            rows=[],
        )
    assert response["act"] == "unavailable"


def test_unsupported_anchor_becomes_unknown():
    from app.application.ports.math_engine import MathResult
    from app.application.workflows.blueprint_planner import (
        verify_milestone_anchor_detail,
    )

    class Engine:
        def execute(self, request):
            return MathResult(status="unknown", error_code="unsupported")

    result = verify_milestone_anchor_detail(
        Engine(),
        {
            "check_kind": "symbolic_equivalence",
            "canonical_target": "2",
            "verify_request": {"op": "evaluate", "args": {"expression": "1+1"}},
        },
    )
    assert result["status"] == "unknown" and result["reason"] == "unsupported"
