from __future__ import annotations

import json

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import ValidationError as PythonValidationError

from app.agent_specs.catalog import AgentSpec, load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.contracts import validate_output
from app.agent_specs.definitions import DefinitionCatalog, load_definitions
from app.agent_specs.results import AgentResult, completed, result_validator
from app.agent_specs.runtime import GateDecision, execute_workflow
from app.infrastructure.ai.prompts import DynamicPrompt


def test_context_text_cannot_create_additional_template_substitutions():
    prompt = DynamicPrompt("test", "{{first}} {{second}}", {
        "first": {"type": "string"}, "second": {"type": "string"},
    })
    assert prompt.render({"first": "{{second}}", "second": "data"}) == "{{second}} data"


def test_judge_context_rejects_agent_memory_and_history():
    with pytest.raises(TypeError):
        build_context("tutoring.leak-judge", text="候选", task_title=None,
                      problem_summary=None, profile={"private": "data"})
    result = json.loads(build_context("tutoring.visual-leak-judge", text="配图",
                                     task_title="任务", problem_summary="题目"))
    assert result == {"visual": "配图", "task_title": "任务", "problem": "题目"}


def _conditional_spec() -> AgentSpec:
    return AgentSpec.model_validate({
        "kind": "workflow", "id": "demo", "version": "v1", "handler": "demo",
        "entry": "demo.propose",
        "nodes": [
            {"id": "demo.propose", "kind": "agent", "ref": "demo.propose"},
            {"id": "demo.check", "kind": "gate", "ref": "demo.check"},
        ],
        "edges": [
            {"from": "START", "to": "demo.propose"},
            {"from": "demo.propose", "to": "demo.check", "condition": "needs_check"},
            {"from": "demo.propose", "to": "END", "condition": "skip_check"},
            {"from": "demo.check", "to": "END"},
        ],
        "required_gates": [{"ref": "demo.check", "when": "needs_check"}],
    })


def test_conditional_gate_runs_only_when_applicable():
    spec = _conditional_spec()
    visited = []
    handlers = {
        "demo.propose": lambda state: state.update(checked=state["needs_check"]),
        "demo.check": lambda state: visited.append("gate") or GateDecision("allow", "ok"),
    }
    conditions = {
        "needs_check": lambda state: state["needs_check"],
        "skip_check": lambda state: not state["needs_check"],
    }
    result = execute_workflow(spec, handlers=handlers, conditions=conditions, initial_state={"needs_check": False})
    assert isinstance(result["results"]["demo.propose"], AgentResult)
    assert visited == []
    execute_workflow(spec, handlers=handlers, conditions=conditions, initial_state={"needs_check": True})
    assert visited == ["gate"]


@pytest.mark.parametrize("payload,valid", [
    ({"status": "ok", "data": {}, "error_code": None}, True),
    ({"status": "needs_input", "data": {"question": "哪一道？"}, "error_code": None}, True),
    ({"status": "failed", "data": None, "error_code": "invalid_model_candidate"}, True),
    ({"status": "failed", "data": {"rejected": "candidate"}, "error_code": "invalid_model_candidate"}, False),
    ({"status": "failed", "data": None, "error_code": None}, False),
    ({"status": "ok", "data": None, "error_code": None}, False),
    ({"status": "ok", "data": {}, "error_code": "model_transport_error"}, False),
    ({"status": "failed", "data": None, "error_code": "provider secret details"}, False),
])
def test_json_and_python_envelope_contracts_agree(payload, valid):
    if valid:
        result_validator().validate(payload)
        AgentResult.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            result_validator().validate(payload)
        with pytest.raises(PythonValidationError):
            AgentResult.model_validate(payload)


def test_envelope_adapter_preserves_existing_data_and_failure_protocol():
    from app.infrastructure.ai.errors import ModelGatewayError
    assert completed({"content": "原回复"}).unwrap() == {"content": "原回复"}
    with pytest.raises(ModelGatewayError, match="invalid_model_candidate"):
        AgentResult(status="failed", error_code="invalid_model_candidate").unwrap()


def test_missing_branch_handler_is_rejected_before_any_side_effect():
    effects = []
    with pytest.raises(ValueError, match="missing handler"):
        execute_workflow(
            _conditional_spec(),
            handlers={"demo.propose": lambda state: effects.append("called")},
            conditions={"needs_check": lambda state: False, "skip_check": lambda state: True},
        )
    assert effects == []


def test_unknown_gate_and_skipped_required_gate_fail_closed():
    spec = _conditional_spec()
    conditions = {
        "needs_check": lambda state: state["needs_check"],
        "skip_check": lambda state: not state["needs_check"],
    }
    with pytest.raises(ValueError, match="returned unknown"):
        execute_workflow(
            spec, initial_state={"needs_check": True}, conditions=conditions,
            handlers={"demo.propose": lambda state: None,
                      "demo.check": lambda state: GateDecision("unknown", "timeout")},
        )
    with pytest.raises(ValueError, match="required Gate.*skipped"):
        execute_workflow(
            spec.model_copy(update={"required_gates": [{"ref": "demo.check", "when": "skip_check"}]}),
            initial_state={"needs_check": False},
            conditions={"needs_check": lambda state: state["needs_check"],
                        "skip_check": lambda state: not state["needs_check"]},
            handlers={"demo.propose": lambda state: None,
                      "demo.check": lambda state: GateDecision("allow", "ok")},
        )


def test_model_order_and_dual_output_contract():
    catalog = load_catalog()
    unit = load_definitions().units["tutoring.turn"]
    assert [model.component_id for model in unit.models] == ["tutoring.turn", "tutoring.turn-backup"]
    assert [catalog.component("tutoring", "attempt", i).model for i in range(2)] == [
        model.name for model in unit.models
    ]
    validate_output(load_definitions().units["companion.intent"], {"intent": "tutoring"})
    with pytest.raises(ValidationError):
        validate_output(load_definitions().units["companion.intent"], {"intent": "unknown"})


def test_invalid_tool_reference_is_rejected_at_load(tmp_path):
    source = load_definitions().root
    for folder in ("agents", "gates", "tools"):
        (tmp_path / folder).mkdir()
        for path in (source / folder).glob("*.json"):
            data = json.loads(path.read_text())
            if path.name == "tutoring.turn.json":
                data["tools"] = ["tutoring.nonexistent"]
            (tmp_path / folder / path.name).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unknown Tool"):
        DefinitionCatalog(tmp_path)
