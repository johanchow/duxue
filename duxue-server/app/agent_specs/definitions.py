"""Validated access to pinned Admin Agent, Gate, Tool and Workflow artifacts."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_specs.contexts import BUILDERS
from app.agent_specs.results import ERROR_CODES, result_validator

ROOT = Path(__file__).resolve().parents[2] / "agent_specs"
_TOOL_HANDLERS = {
    "tutoring.get_task_context", "tutoring.get_attempt_summary",
    "tutoring.lookup_history", "tool.static_result",
}


class PromptFragmentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    template: str
    variables: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_source(self):
        import re
        names = set(re.findall(r"\{\{([a-z_][a-z_0-9]*)\}\}", self.template))
        if names != set(self.variables):
            raise ValueError(f"{self.id}: prompt variables do not match placeholders")
        for name, declaration in self.variables.items():
            if declaration != {"type": declaration.get("type"), "binding": f"context.{name}"}:
                raise ValueError(f"{self.id}: invalid variable binding {name}")
            if declaration["type"] not in {"string", "array", "object"}:
                raise ValueError(f"{self.id}: invalid variable type {name}")
        return self


class PromptDefinition(PromptFragmentDefinition):
    delivery: Literal["system", "user"] = "system"
    fragments: dict[str, PromptFragmentDefinition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_fragments(self):
        import re
        if self.delivery == "system" and self.variables:
            raise ValueError(f"{self.id}: system prompt cannot use caller variables")
        if any(not re.fullmatch(r"[a-z][a-z_0-9]*", name) for name in self.fragments):
            raise ValueError(f"{self.id}: invalid fragment name")
        ids = [self.id, *(fragment.id for fragment in self.fragments.values())]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.id}: duplicate Prompt ID")
        return self


class ModelDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    name: str
    version: str | None = None
    operation: str | None = None
    temperature: float = Field(ge=0, le=2)
    max_output_tokens: int = Field(gt=0, le=4096)
    timeout_ms: int = Field(gt=0, le=120000)


class ModelUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    id: str
    version: str
    kind: Literal["agent", "gate"]
    implementation: Literal["llm", "judge"]
    agent_label: Literal["planning", "tutoring", "reflection"]
    risk_tier: Literal["protected", "standard"]
    operation: str
    input_contract: str
    output_contract: str
    input_schema: dict
    output_schema: dict | None = None
    verdict_schema: dict | None = None
    provider_output_schema: dict | None = None
    context_builder_id: str
    prompt: PromptDefinition
    tools: list[str]
    error_codes: list[str] | None = None
    models: list[ModelDefinition] = Field(min_length=1)
    accepts_images: bool = True
    requires_agent_switch: bool = True
    on_error: Literal["deny", "abort", "drop_optional_output"] | None = None
    safety_class: Literal["protected", "standard"] | None = None

    @model_validator(mode="after")
    def valid_contract(self):
        if self.kind == "agent":
            if (self.error_codes is None or not set(self.error_codes).issubset(ERROR_CODES)
                    or "agent_execution_failed" not in self.error_codes):
                raise ValueError(f"{self.id}: invalid Agent error codes")
            if self.implementation != "llm" or self.output_schema is None or self.verdict_schema is not None:
                raise ValueError(f"{self.id}: invalid Agent contract")
            if self.on_error is not None or self.safety_class is not None:
                raise ValueError(f"{self.id}: Gate fields on Agent")
        elif (self.implementation != "judge" or self.verdict_schema is None
              or self.output_schema is not None or self.on_error is None or self.safety_class is None):
            raise ValueError(f"{self.id}: invalid Gate contract")
        for schema in (self.input_schema, self.output_schema, self.verdict_schema, self.provider_output_schema):
            if schema is not None:
                Draft202012Validator.check_schema(schema)
                if schema.get("type") != "object":
                    raise ValueError(f"{self.id}: schema must describe an object")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError(f"{self.id}: duplicate Tool reference")
        if len({model.component_id for model in self.models}) != len(self.models):
            raise ValueError(f"{self.id}: duplicate model component ID")
        return self


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    id: str
    version: str
    kind: Literal["tool"]
    description: str
    input_schema: dict
    output_schema: dict
    handler_id: str
    access: Literal["read", "write"]
    static_result: dict | None = None

    @model_validator(mode="after")
    def valid_static_result(self):
        for schema in (self.input_schema, self.output_schema):
            Draft202012Validator.check_schema(schema)
        if self.handler_id == "tool.static_result":
            if self.access != "read" or self.static_result is None:
                raise ValueError(f"{self.id}: static Tool requires a read-only result")
            if self.input_schema.get("type") != "object" or self.output_schema.get("type") != "object":
                raise ValueError(f"{self.id}: static Tool schemas must describe objects")
            # Use ValueError so malformed config always has a Pydantic validation error.
            if not Draft202012Validator(self.output_schema).is_valid(self.static_result):
                raise ValueError(f"{self.id}: static result violates output_schema")
        elif self.static_result is not None:
            raise ValueError(f"{self.id}: static_result requires the static handler")
        return self


class CodeGateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    id: str
    version: str
    kind: Literal["gate"]
    implementation: Literal["code"]
    handler_id: str
    input_schema: dict
    verdict_schema: dict
    on_error: Literal["deny", "abort", "drop_optional_output"]
    safety_class: Literal["protected", "standard"]


class CodeAgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = None
    description: str | None = None
    id: str
    version: str
    kind: Literal["agent"]
    implementation: Literal["code"]
    handler_id: Literal["planning", "tutoring", "reflection"]
    input_schema: dict
    output_schema: dict
    error_codes: list[str]


class DefinitionCatalog:
    def __init__(self, root: Path):
        result_validator()
        self.root = root
        self.artifact_digest: str | None = None
        self.workflow_catalog = None
        self.units: dict[str, ModelUnit] = {}
        self.tools: dict[str, ToolDefinition] = {}
        self.code_gates: dict[str, CodeGateDefinition] = {}
        self.code_agents: dict[str, CodeAgentDefinition] = {}
        self.components: dict[str, tuple[ModelUnit, int]] = {}
        for directory, kind in (("agents", "agent"), ("gates", "gate")):
            for path in sorted((root / directory).glob("*.json")):
                raw = json.loads(path.read_text(encoding="utf-8"))
                if kind == "agent" and raw.get("implementation") == "code":
                    agent = CodeAgentDefinition.model_validate(raw)
                    if path.stem != agent.id or agent.id != agent.handler_id + ".session-turn":
                        raise ValueError(f"invalid code Agent file {path}")
                    if not set(agent.error_codes).issubset(ERROR_CODES) or "agent_execution_failed" not in agent.error_codes:
                        raise ValueError(f"{agent.id}: unknown Agent error code")
                    Draft202012Validator.check_schema(agent.input_schema)
                    Draft202012Validator.check_schema(agent.output_schema)
                    self.code_agents[agent.id] = agent
                    continue
                if kind == "gate" and raw.get("implementation") == "code":
                    gate = CodeGateDefinition.model_validate(raw)
                    if gate.id != path.stem or gate.id in self.code_gates:
                        raise ValueError(f"invalid code Gate file {path}")
                    if gate.handler_id not in {"tutoring.check_authority", "planning.confirmation_gate",
                                               "tutoring.tool_budget", "tutoring.candidate_schema",
                                               "tutoring.visual_schema", "tutoring.candidate_exit",
                                               "tutoring.visual", "tutoring.output_safety"}:
                        raise ValueError(f"{gate.id}: unknown Gate handler")
                    Draft202012Validator.check_schema(gate.input_schema)
                    Draft202012Validator.check_schema(gate.verdict_schema)
                    self.code_gates[gate.id] = gate
                    continue
                unit = ModelUnit.model_validate(raw)
                if unit.kind != kind or path.stem != unit.id or unit.id in self.units:
                    raise ValueError(f"invalid {kind} file {path}")
                self.units[unit.id] = unit
                for index, model in enumerate(unit.models):
                    if model.component_id in self.components:
                        raise ValueError(f"duplicate component {model.component_id}")
                    self.components[model.component_id] = unit, index
        for path in sorted((root / "tools").glob("*.json")):
            tool = ToolDefinition.model_validate_json(path.read_text(encoding="utf-8"))
            if path.stem != tool.id or tool.id in self.tools:
                raise ValueError(f"invalid Tool file {path}")
            if tool.handler_id not in _TOOL_HANDLERS:
                raise ValueError(f"{tool.id}: unknown Tool handler {tool.handler_id}")
            if tool.access != "read":
                raise ValueError(f"{tool.id}: existing tutor Tools must remain read-only")
            Draft202012Validator.check_schema(tool.input_schema)
            Draft202012Validator.check_schema(tool.output_schema)
            self.tools[tool.id] = tool
        from app.agent_specs.contracts import has_python_contract
        prompt_ids: set[str] = set()
        for unit in self.units.values():
            for prompt in (unit.prompt, *unit.prompt.fragments.values()):
                if prompt.id in prompt_ids:
                    raise ValueError(f"duplicate Prompt ID {prompt.id}")
                prompt_ids.add(prompt.id)
            if unit.context_builder_id not in BUILDERS:
                raise ValueError(f"{unit.id}: unknown Context Builder {unit.context_builder_id}")
            if unit.context_builder_id != unit.id.replace("-", "_") + ".context":
                raise ValueError(f"{unit.id}: Context Builder is outside this unit's authorized scope")
            if not has_python_contract(unit.id):
                raise ValueError(f"{unit.id}: missing Python contract")
            for tool_id in unit.tools:
                if tool_id not in self.tools:
                    raise ValueError(f"{unit.id}: unknown Tool {tool_id}")
        if set(self.units) & set(self.code_gates):
            raise ValueError("Agent/Gate ID collision")
        for unit_id in ("tutoring.turn", "tutoring.image-target", "tutoring.leak-judge", "tutoring.visual-leak-judge"):
            unit = self.units.get(unit_id)
            if unit is None or unit.risk_tier != "protected":
                raise ValueError(f"{unit_id}: protected model definition is required")
            if unit.kind == "gate" and (unit.safety_class != "protected" or unit.on_error != "deny"):
                raise ValueError(f"{unit_id}: unsafe Gate policy")
        for gate_id, policy in {"tutoring.authority": "deny", "planning.confirmation-gate": "abort"}.items():
            gate = self.code_gates.get(gate_id)
            if gate is None or gate.safety_class != "protected" or gate.on_error != policy:
                raise ValueError(f"{gate_id}: unsafe Gate policy")
        if not self.units or not self.tools:
            raise ValueError("Agent and Tool definitions are required")

    def component(self, component_id: str) -> tuple[ModelUnit, int]:
        try:
            return self.components[component_id]
        except KeyError as error:
            raise KeyError(f"unknown AI component: {component_id}") from error

    def definition_digest(self, component_id: str) -> str:
        unit, _ = self.component(component_id)
        payload = {"unit": unit.model_dump(mode="json"),
                   "tools": [self.tools[tool_id].model_dump(mode="json") for tool_id in unit.tools]}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=1)
def base_definitions() -> DefinitionCatalog:
    from app.agent_specs.configuration import read_snapshot, _offline_catalog
    if _offline_catalog is not None:
        return _offline_catalog
    from app.agent_specs.admin_bundle import compile_bundle
    import os
    mode = os.getenv("AGENT_CONFIG_SOURCE", "admin" if os.getenv("APP_ENV") in {"production", "prod"} else "snapshot")
    if mode == "admin":
        from app.agent_specs.release_runtime import AgentConfigurationUnavailable
        raise AgentConfigurationUnavailable("Admin运行配置尚未初始化，拒绝读取离线快照兜底")
    if mode != "snapshot":
        raise ValueError("AGENT_CONFIG_SOURCE只允许admin或snapshot")
    try:
        return compile_bundle(read_snapshot()["bundle"]).catalog
    except (ValueError, OSError) as error:
        from app.agent_specs.release_runtime import AgentConfigurationUnavailable
        raise AgentConfigurationUnavailable(str(error)) from error


_current: ContextVar[DefinitionCatalog | None] = ContextVar("agent_definitions", default=None)


def load_definitions() -> DefinitionCatalog:
    return active_definitions() or base_definitions()


def pinned_definitions() -> DefinitionCatalog | None:
    return _current.get()


def active_definitions() -> DefinitionCatalog | None:
    pinned = _current.get()
    if pinned is not None:
        return pinned
    # Lazy access avoids startup import cycles. One runtime owns the atomic
    # published pointer; standalone model adapters also see its active version.
    import sys
    module = sys.modules.get("app.agent_specs.release_runtime")
    runtime = getattr(module, "runtime", None)
    if runtime is not None:
        return runtime.definitions()
    return None


@contextmanager
def use_definitions(definitions: DefinitionCatalog):
    token = _current.set(definitions)
    try:
        yield
    finally:
        _current.reset(token)
