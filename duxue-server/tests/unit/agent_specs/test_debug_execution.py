from types import SimpleNamespace

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import snapshot_bundle
from app.agent_specs.debug_contracts import DebugInput, resolve_target
from app.agent_specs.debug_worker import execute
from app.agent_specs.execution_trace import recorder
from app.infrastructure.ai.errors import ModelGatewayError


def test_agent_targets_are_locked_and_code_components_never_fall_through_to_tutor():
    catalog = compile_bundle(snapshot_bundle()).catalog
    with pytest.raises(ValueError, match="does not belong"):
        resolve_target(
            DebugInput(
                content="test",
                target_kind="agent",
                target_id="tutoring.turn",
                component_id="companion.intent",
            ),
            catalog,
        )
    with pytest.raises(ValueError, match="no independent"):
        resolve_target(
            DebugInput(
                content="test", target_kind="agent", target_id="tutoring.authority"
            ),
            catalog,
        )
    with pytest.raises(ValueError, match="no standalone"):
        resolve_target(
            DebugInput(content="test", target_kind="workflow", target_id="planning"),
            catalog,
        )
    assert (
        resolve_target(
            DebugInput(
                content="test",
                target_kind="agent",
                target_id="tutoring.turn",
                component_id="tutoring.turn-backup",
            ),
            catalog,
        )["component_id"]
        == "tutoring.turn-backup"
    )


def setup_provider(monkeypatch, function):
    from app.bootstrap import settings as settings_module
    from app.infrastructure.ai import components

    monkeypatch.setattr(components, "invoke_json_component", function)
    monkeypatch.setattr(
        settings_module,
        "settings",
        SimpleNamespace(dashscope_api_key="unit-test", agent_model_timeout_seconds=8),
    )


def test_failed_debug_retains_input_failed_model_and_executor_identity(monkeypatch):
    def fail(**kwargs):
        raise ModelGatewayError("model_transport_error")

    setup_provider(monkeypatch, fail)
    bundle = snapshot_bundle()
    result = execute(
        {
            "bundle": bundle,
            "input": {
                "content": "hello",
                "target_kind": "agent",
                "target_id": "companion.intent",
            },
        }
    )
    assert result["status"] == "failed"
    assert result["covered_components"] == []
    assert result["steps"][0]["input"][-1]["content"] == "hello"
    assert result["events"][0]["status"] == "failed"
    assert len(result["executor_digest"]) == 64
    assert recorder() is None


def test_single_agent_debug_never_runs_judge_tools_or_backup_unless_selected(
    monkeypatch,
):
    calls = []

    def reply(**kwargs):
        calls.append(kwargs["spec"].component_id)
        return {"test": "output"}

    setup_provider(monkeypatch, reply)
    result = execute(
        {
            "bundle": snapshot_bundle(),
            "input": {
                "content": "test",
                "target_kind": "agent",
                "target_id": "tutoring.turn",
                "component_id": "tutoring.turn-backup",
            },
        }
    )
    assert result["status"] == "succeeded"
    assert calls == ["tutoring.turn-backup"]
    assert result["covered_components"] == calls


def test_workflow_debug_uses_real_executor_with_edge_and_node_data(monkeypatch):
    setup_provider(monkeypatch, lambda **kwargs: {"aspects": []})
    result = execute(
        {
            "bundle": snapshot_bundle(),
            "input": {
                "content": "今天我学会了乘法",
                "target_kind": "workflow",
                "target_id": "review-aspects",
            },
        }
    )
    assert result["status"] == "succeeded"
    node = next(
        event
        for event in result["events"]
        if event.get("node_id") == "review-aspects.run"
    )
    assert node["input"] == {"results": {}, "visited_gates": []}
    assert node["output"]["data"] == {"aspects": []}
    assert (
        len([e for e in result["events"] if e["kind"] == "edge" and e["selected"]]) == 2
    )


def test_tutoring_workflow_is_isolated_and_includes_domain_and_gate_nodes(monkeypatch):
    from tests.support.fakes import tutor_raw

    setup_provider(
        monkeypatch,
        lambda **kwargs: tutor_raw(
            "answer", "光合作用需要光。", relation="none", student_move="other"
        ),
    )
    result = execute(
        {
            "bundle": snapshot_bundle(),
            "input": {
                "content": "什么是光合作用",
                "target_kind": "workflow",
                "target_id": "tutoring",
            },
        }
    )
    assert result["status"] == "succeeded", result
    ids = {event.get("node_id") for event in result["events"]}
    assert {
        "tutoring.turn",
        "tutoring.model_loop",
        "tutoring.output_safety",
        "tutoring.result",
    } <= ids
    assert any(
        event.get("workflow_id") == "tutoring"
        and event.get("kind") == "edge"
        and event.get("selected")
        for event in result["events"]
    )
    assert result["sandbox_effects"]["messages"]
    assert result["output"]["next_interaction"]["content"]


def test_reflection_executes_confirmation_only_in_disposable_state(monkeypatch):
    setup_provider(
        monkeypatch,
        lambda **kwargs: pytest.fail("reflection confirmation should not call a model"),
    )
    result = execute(
        {
            "bundle": snapshot_bundle(),
            "input": {
                "content": "今天我学会了乘法",
                "target_kind": "workflow",
                "target_id": "reflection",
                "context": {"review_date": "2026-11-09", "review_feeling": "开心"},
            },
        }
    )
    assert result["status"] == "succeeded", result
    assert result["output"]["run_status"] == "closed"
    assert (
        result["sandbox_effects"]["self_reviews"][0]["reflection"] == "今天我学会了乘法"
    )
    assert result["model_requests"] == 0
