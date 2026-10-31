"""Agent definitions are executable inventory, not a second hand-maintained diagram."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.agent_specs.catalog import AgentCatalog, load_catalog, render_mermaid
from app.agent_specs.definitions import load_definitions


def test_catalog_covers_route_business_nodes_gates_tools_and_components():
    catalog = load_catalog()
    assert set(catalog.specs) == {
        "companion", "planning", "tutoring", "tutoring-vet", "tutoring-retry", "reflection", "task-intake", "review-aspects",
    }
    assert catalog.step("route", "intent_route").owner == "companion"
    assert catalog.step("check", "tutoring.exit_gate").required
    assert catalog.step("check", "planning.confirmation_gate").required
    assert set(load_definitions().units["tutoring.turn"].tools) == {
        "tutoring.get_task_context", "tutoring.get_attempt_summary",
        "tutoring.lookup_history", "tutoring.widget_guidelines",
    }
    assert catalog.component("companion", "intent_route").component_id == "companion.intent"
    assert catalog.component_by_id("tutoring-vet", "tutoring.leak-judge").component_id == "tutoring.leak-judge"
    assert catalog.step("check", "tutoring.text_leak").required
    assert catalog.component_identity("companion.intent").node_id == "companion.intent_route"
    leak = catalog.step("check", "tutoring.text_leak")
    assert (leak.unit_kind, leak.unit_id, leak.node_id) == ("gate", "tutoring.leak-judge", "tutoring-vet.text_leak")
    assert leak.unit_version == load_definitions().units["tutoring.leak-judge"].version
    attempt = catalog.step("node", "tutoring.attempt")
    assert (attempt.unit_kind, attempt.unit_id, attempt.node_id) == ("agent", "tutoring.turn", "tutoring.attempt")
    tool = catalog.step("tool", "get_attempt_summary")
    assert (tool.unit_kind, tool.unit_id) == ("tool", "tutoring.get_attempt_summary")
    assert catalog.component("task-intake", "run").component_id == "task.intake"
    assert catalog.component("review-aspects", "run").component_id == "evaluation.review-aspects"


def test_missing_required_guardrail_fails_catalog_load(tmp_path: Path):
    source = load_catalog().directory
    for source_file in (source / "workflows").glob("*.json"):
        payload = json.loads(source_file.read_text())
        if source_file.stem == "tutoring":
            payload["nodes"] = [node for node in payload["nodes"] if node["id"] != "tutoring.exit_gate"]
        (tmp_path / source_file.name).write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="tutoring.exit_gate"):
        AgentCatalog.from_directory(tmp_path)


@pytest.mark.parametrize(
    ("agent", "change", "error"),
    [
        ("companion", "unknown_component", "unknown Agent reference"),
        ("companion", "broken_edge", "unknown edge target"),
        ("tutoring", "unsafe_limit", "unsafe limit"),
        ("tutoring", "missing_required", "required checks list differs"),
        ("planning", "wrong_handler", "workflow handler must match"),
        ("companion", "unknown_handler", "unknown action handler"),
        ("companion", "unknown_condition", "unknown condition"),
    ],
)
def test_invalid_definition_fails_load(tmp_path: Path, agent: str, change: str, error: str):
    for source_file in (load_catalog().directory / "workflows").glob("*.json"):
        payload = json.loads(source_file.read_text())
        if source_file.stem == agent:
            if change == "unknown_component":
                payload["nodes"][0]["ref"] = "missing.component"
            elif change == "broken_edge":
                payload["edges"][1]["to"] = "companion.missing"
            elif change == "unsafe_limit":
                payload["limits"]["tool_calls"] = 999
            elif change == "wrong_handler":
                payload["handler"] = "reflection"
            elif change == "unknown_handler":
                payload["nodes"][-1]["handler_id"] = "unregistered_handler"
            elif change == "unknown_condition":
                payload["edges"][1]["condition_id"] = "unregistered_condition"
            else:
                payload["required_checks"].remove("tutoring.exit_gate")
        (tmp_path / source_file.name).write_text(json.dumps(payload))
    with pytest.raises((ValueError, KeyError), match=error):
        AgentCatalog.from_directory(tmp_path)


def test_transition_must_be_declared():
    catalog = load_catalog()
    catalog.require_edge("companion", "intent_route", "switch_confirm", "cross_scene")
    with pytest.raises(ValueError, match="undeclared transition"):
        catalog.require_edge("companion", "intent_route", "switch_confirm", "direct")


def test_literal_agent_trace_steps_are_declared():
    catalog = load_catalog()
    app_root = Path(__file__).resolve().parents[3] / "app"
    for path in app_root.rglob("*.py"):
        for call in (item for item in ast.walk(ast.parse(path.read_text())) if isinstance(item, ast.Call)):
            if not isinstance(call.func, ast.Name):
                continue
            if call.func.id == "agent_step_span" and len(call.args) >= 2:
                kind, name = call.args[:2]
                if isinstance(kind, ast.Constant) and isinstance(name, ast.Constant):
                    catalog.step(kind.value, name.value)
            elif call.func.id == "traced_agent_node" and call.args:
                name = call.args[0]
                if isinstance(name, ast.Constant):
                    catalog.step("node", name.value)
            elif call.func.id == "planning_stage_span" and call.args:
                name = call.args[0]
                if isinstance(name, ast.Constant):
                    catalog.step("stage", f"planning.{name.value}")


def test_generated_workflow_document_matches_definitions():
    catalog = load_catalog()
    target = Path(__file__).resolve().parents[4] / "docs" / "technical" / "agent-flow-current.md"
    assert target.read_text() == render_mermaid(catalog)
