"""Load the single workflow inventory used by runtime and diagrams.

JSON selects reviewed node and component IDs.  It never imports arbitrary
handlers, evaluates expressions, grants permissions or implements guardrails.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_specs.definitions import load_definitions
from app.agent_specs.registrations import WORKFLOW_BINDINGS
from app.infrastructure.ai.components import COMPONENTS, ComponentSpec

_DIRECTORY = Path(__file__).resolve().parents[2] / "agent_specs"
_REQUIRED_CHECKS = {
    "planning": {"planning.confirmation_gate"},
    "tutoring": {
        "tutoring.candidate_schema", "tutoring.exit_gate", "tutoring.output_safety", "tutoring.candidate_exit",
        "tutoring.visual",
    },
}
_REQUIRED_GATES = {
    "tutoring-vet": {
        ("tutoring.authority", "always"),
        ("tutoring.leak-judge", "requires_text_leak"),
        ("tutoring.visual-leak-judge", "requires_visual_leak"),
    },
}
_CONDITIONS = {
    "authority_denied", "authority_allowed_needs_leak_check", "authority_allowed_no_leak_check",
    "text_denied", "text_allowed_with_visual", "text_allowed_no_visual",
    "always", "requires_text_leak", "requires_visual_leak",
}
_MAX_LIMITS = {"model_calls": 4, "tool_calls": 3}
_BUSINESS = {"planning", "tutoring", "reflection"}


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["agent", "gate", "action"]
    trace_kind: Literal["route", "node", "stage", "check"] | None = None
    ref: str | None = None
    trace: str | None = None
    handler: str | None = Field(default=None, alias="handler_id")
    graph_key: str | None = None
    parent: str | None = None
    required: bool = False

    @model_validator(mode="after")
    def implementation_reference(self):
        if self.kind == "action":
            if not self.handler or self.ref:
                raise ValueError(f"{self.id}: action requires handler and forbids ref")
        elif not self.ref or self.handler:
            raise ValueError(f"{self.id}: Agent/Gate requires ref and forbids handler")
        return self


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    condition: str | None = Field(default=None, alias="condition_id")
    via: str | None = None


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["workflow"]
    id: str
    version: str
    handler: str
    invocation_agent: str | None = None
    entry: str
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]
    targets: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    required_gates: list[dict[str, str]] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_topology(self):
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError(f"{self.id}: duplicate node ID")
        if self.entry not in nodes:
            raise ValueError(f"{self.id}: missing entry {self.entry}")
        for node in self.nodes:
            if not node.id.startswith(f"{self.id}."):
                raise ValueError(f"{self.id}: foreign node {node.id}")
            if node.parent and node.parent not in nodes:
                raise ValueError(f"{self.id}: missing parent {node.parent}")
            if node.parent == node.id:
                raise ValueError(f"{self.id}: self parent {node.id}")
        for edge in self.edges:
            if edge.source not in nodes and edge.source != "START":
                raise ValueError(f"{self.id}: unknown edge source {edge.source}")
            if edge.target not in nodes and edge.target != "END":
                raise ValueError(f"{self.id}: unknown edge target {edge.target}")
            if edge.via and edge.via not in nodes:
                raise ValueError(f"{self.id}: unknown edge router {edge.via}")
            if self.id == "tutoring-vet" and edge.condition and edge.condition not in _CONDITIONS:
                raise ValueError(f"{self.id}: unknown condition {edge.condition}")
        if not any(edge.source == "START" and edge.target == self.entry for edge in self.edges):
            raise ValueError(f"{self.id}: START must enter {self.entry}")
        if not any(edge.target == "END" for edge in self.edges):
            raise ValueError(f"{self.id}: END is unreachable")
        reachable = {"START"}
        while True:
            discovered = reachable | {
                edge.target for edge in self.edges if edge.source in reachable
            }
            if discovered == reachable:
                break
            reachable = discovered
        if "END" not in reachable:
            raise ValueError(f"{self.id}: END is unreachable from START")
        for node in self.nodes:
            if (not node.parent and node.trace_kind != "stage"
                    and node.id not in reachable
                    and node.id not in {edge.via for edge in self.edges}):
                raise ValueError(f"{self.id}: unreachable flow node {node.id}")
            seen = {node.id}
            parent = node.parent
            while parent:
                if parent in seen:
                    raise ValueError(f"{self.id}: parent cycle at {parent}")
                seen.add(parent)
                parent = nodes[parent].parent
        for check in self.required_checks:
            if check not in nodes or not nodes[check].required:
                raise ValueError(f"{self.id}: missing required check {check}")
        if self.id in _REQUIRED_GATES:
            declared = {(item.get("ref"), item.get("when")) for item in self.required_gates}
            if declared != _REQUIRED_GATES[self.id]:
                raise ValueError(f"{self.id}: required Gate baseline differs")
            for item in self.required_gates:
                if item["when"] not in _CONDITIONS or not any(
                    node.kind == "gate" and node.ref == item["ref"] for node in self.nodes
                ):
                    raise ValueError(f"{self.id}: invalid required Gate {item}")
        declared_checks = {node.id for node in self.nodes
                           if self.id in _REQUIRED_CHECKS
                           and node.required}
        if declared_checks != set(self.required_checks):
            raise ValueError(f"{self.id}: required checks list differs from nodes")
        for limit, value in self.limits.items():
            if limit not in _MAX_LIMITS or value < 1 or value > _MAX_LIMITS[limit]:
                raise ValueError(f"{self.id}: unsafe limit {limit}={value}")
        return self

    def node(self, name: str) -> NodeSpec:
        node_id = name if name.startswith(f"{self.id}.") else f"{self.id}.{name}"
        return next(node for node in self.nodes if node.id == node_id)


class StepIdentity(BaseModel):
    owner: str
    version: str
    node_id: str
    kind: str
    required: bool
    # The configured object this step executes. Distinct from ``kind``, which is
    # only the trace shape (route, node, stage, check, tool).
    unit_kind: Literal["agent", "gate", "tool", "action"]
    unit_id: str
    unit_version: str


def _configured_unit(ref: str) -> tuple[str, str, str]:
    """Return the definition kind, stable id and version for an Agent, Gate or Tool."""
    definitions = load_definitions()
    for collection in (definitions.units, definitions.code_agents, definitions.code_gates, definitions.tools):
        item = collection.get(ref)
        if item is not None:
            return item.kind, item.id, item.version
    raise ValueError(f"unknown configured unit {ref}")


def _node_unit(spec: AgentSpec, node: NodeSpec) -> tuple[str, str, str]:
    """An action lives only in its Workflow; an Agent or Gate keeps its own version."""
    if node.kind == "action":
        return "action", node.id, spec.version
    return _configured_unit(node.ref or "")


def _node_components(node: NodeSpec) -> list[str]:
    if node.ref and node.ref in load_definitions().units:
        return [model.component_id for model in load_definitions().units[node.ref].models]
    return []


class AgentCatalog:
    def __init__(self, specs: dict[str, AgentSpec], directory: Path):
        self.specs = specs
        self.directory = directory
        self._steps: dict[tuple[str, str], StepIdentity] = {}
        self._components: dict[str, StepIdentity] = {}
        referenced: set[str] = set()
        for spec in specs.values():
            registration = WORKFLOW_BINDINGS[spec.id]
            handlers = {node.handler for node in spec.nodes if node.handler}
            conditions = {edge.condition for edge in spec.edges if edge.condition}
            conditions.update(gate["when"] for gate in spec.required_gates)
            if handlers - registration["handlers"]:
                raise ValueError(f"{spec.id}: unknown action handler")
            if conditions - registration["conditions"]:
                raise ValueError(f"{spec.id}: unknown condition")
            if spec.id in _BUSINESS and spec.invocation_agent != spec.id + ".session-turn":
                raise ValueError(f"{spec.id}: invalid code Agent binding")
            if spec.invocation_agent and spec.invocation_agent not in load_definitions().code_agents:
                raise ValueError(f"{spec.id}: unknown code Agent")
            for node in spec.nodes:
                if node.kind == "agent" and node.ref not in load_definitions().units and node.ref not in load_definitions().code_agents:
                    raise ValueError(f"{node.id}: unknown Agent reference {node.ref}")
                if node.kind == "gate" and node.ref not in load_definitions().code_gates and (
                    node.ref not in load_definitions().units or load_definitions().units[node.ref].kind != "gate"
                ):
                    raise ValueError(f"{node.id}: unknown Gate reference {node.ref}")
                for component_id in _node_components(node):
                    COMPONENTS.get(component_id)
                    referenced.add(component_id)
                    if component_id in self._components:
                        raise ValueError(f"component assigned to multiple nodes: {component_id}")
                    unit_kind, unit_id, unit_version = _node_unit(spec, node)
                    self._components[component_id] = StepIdentity(
                        owner=spec.id, version=spec.version, node_id=node.id,
                        kind=node.kind, required=node.required,
                        unit_kind=unit_kind, unit_id=unit_id, unit_version=unit_version,
                    )
                if node.trace:
                    kind = node.trace_kind or ("check" if node.kind == "gate" else "node")
                    key = (kind, node.trace)
                    if key in self._steps:
                        raise ValueError(f"duplicate trace step {key}")
                    unit_kind, unit_id, unit_version = _node_unit(spec, node)
                    self._steps[key] = StepIdentity(
                        owner=spec.id, version=spec.version, node_id=node.id,
                        kind=kind, required=node.required,
                        unit_kind=unit_kind, unit_id=unit_id, unit_version=unit_version,
                    )
        missing_components = {item.component_id for item in COMPONENTS.all()} - referenced
        if missing_components:
            raise ValueError(f"unlisted components: {sorted(missing_components)}")
        tutoring = self.spec("tutoring")
        for tool_id in load_definitions().units["tutoring.turn"].tools:
            trace_name = tool_id.split(".", 1)[1]
            unit_kind, unit_id, unit_version = _configured_unit(tool_id)
            self._steps["tool", trace_name] = StepIdentity(
                owner="tutoring", version=tutoring.version,
                node_id=tool_id, kind="tool", required=False,
                unit_kind=unit_kind, unit_id=unit_id, unit_version=unit_version,
            )
        self._steps["tool", "unknown_tool"] = StepIdentity(
            owner="tutoring", version=tutoring.version,
            node_id="tutoring.unknown_tool", kind="tool", required=False,
            unit_kind="tool", unit_id="tutoring.unknown_tool", unit_version=tutoring.version,
        )
        for agent, checks in _REQUIRED_CHECKS.items():
            spec = self.spec(agent)
            if not checks.issubset(set(spec.required_checks)):
                raise ValueError(f"{agent}: missing required checks {sorted(checks - set(spec.required_checks))}")
        for agent in _BUSINESS:
            if self.spec(agent).handler != agent:
                raise ValueError(f"{agent}: workflow handler must match its domain")
        if self.spec("companion").handler != "coordinator":
            raise ValueError("companion: handler must be coordinator")
        if set(self.spec("companion").targets) != _BUSINESS | {"clarify", "safety"}:
            raise ValueError("companion: route targets differ from business contexts")
        if set(load_definitions().units["tutoring.turn"].tools) != {
            "tutoring.get_task_context", "tutoring.get_attempt_summary",
            "tutoring.lookup_history", "tutoring.widget_guidelines",
        }:
            raise ValueError("tutoring: tool permissions differ from code-owned handlers")

    @classmethod
    def from_directory(cls, directory: Path) -> AgentCatalog:
        specs = {}
        workflow_dir = directory / "workflows" if (directory / "workflows").is_dir() else directory
        for path in sorted(workflow_dir.glob("*.json")):
            spec = AgentSpec.model_validate_json(path.read_text(encoding="utf-8"))
            if path.stem != spec.id or spec.id in specs:
                raise ValueError(f"invalid agent file {path.name}")
            specs[spec.id] = spec
        if set(specs) != {"companion", *_BUSINESS, "task-intake", "review-aspects", "tutoring-vet", "tutoring-retry"}:
            raise ValueError(f"agent definitions missing or unexpected: {sorted(specs)}")
        return cls(specs, directory)

    def spec(self, agent_id: str) -> AgentSpec:
        return self.specs[agent_id]

    def step(self, kind: str, trace_name: str) -> StepIdentity:
        try:
            return self._steps[kind, trace_name]
        except KeyError as error:
            raise ValueError(f"unregistered agent step: {kind}/{trace_name}") from error

    def component(self, agent_id: str, node_name: str, index: int = 0) -> ComponentSpec:
        node = self.spec(agent_id).node(node_name)
        return COMPONENTS.get(_node_components(node)[index])

    def component_by_id(self, agent_id: str, component_id: str) -> ComponentSpec:
        if not any(component_id in _node_components(node)
                   for node in self.spec(agent_id).nodes):
            raise ValueError(f"{agent_id}: component {component_id} is not declared")
        return COMPONENTS.get(component_id)

    def component_identity(self, component_id: str) -> StepIdentity:
        return self._components[component_id]

    def require_edge(self, agent_id: str, source: str, target: str,
                     condition: str | None = None) -> None:
        spec = self.spec(agent_id)
        source_id = source if source == "START" else spec.node(source).id
        target_id = target if target == "END" else spec.node(target).id
        if not any(edge.source == source_id and edge.target == target_id
                   and edge.condition == condition for edge in spec.edges):
            raise ValueError(f"{agent_id}: undeclared transition {source_id} -> {target_id} ({condition})")

    def expanded(self, agent_id: str) -> dict:
        spec = self.spec(agent_id)
        result = spec.model_dump(by_alias=True)
        result["component_details"] = [
            {
                "id": component.component_id,
                "version": component.version,
                "model": component.model,
                "prompt_id": component.prompt.id,
                "prompt_text": getattr(component.prompt, "text", getattr(component.prompt, "template", None)),
                "prompt_builder": getattr(component.prompt, "builder", None),
                "input_contract": component.input_contract,
                "output_contract": component.output_contract,
            }
            for component in COMPONENTS.all()
            if any(component.component_id in _node_components(node) for node in spec.nodes)
        ]
        return result


@lru_cache(maxsize=1)
def load_catalog() -> AgentCatalog:
    return AgentCatalog.from_directory(_DIRECTORY)


def render_mermaid(catalog: AgentCatalog) -> str:
    lines = [
        "# 当前 Agent 流程图（自动生成）",
        "",
        "> 由 `duxue-server/agent_specs/workflows/*.json` 生成；编辑定义后运行 `cd duxue-server && .venv/bin/python -m app.agent_specs export`。",
        "> 实线表示主要执行路径，虚线表示节点内部的条件步骤；门禁实际执行条件仍由代码裁决。",
        "> 独立 API 调用有各自的 Workflow；未连接的节点表示会话外阶段。",
        "",
    ]
    for spec in catalog.specs.values():
        lines.extend([f"## {spec.id} · {spec.version}", "", "```mermaid", "flowchart TD"])
        safe_id = spec.id.replace("-", "_")
        names = {node.id: f"{safe_id}_{node.id.split('.')[-1]}" for node in spec.nodes}
        names.update({"START": f"{safe_id}_START", "END": f"{safe_id}_END"})
        lines.append(f'  {names["START"]}([START])')
        lines.append(f'  {names["END"]}([END])')
        for node in spec.nodes:
            shape = "{{{}}}" if node.kind in {"check", "gate"} else "[{}]"
            lines.append(f"  {names[node.id]}{shape.format(node.id)}")
        for edge in spec.edges:
            label = f"|{edge.condition}|" if edge.condition else ""
            lines.append(f"  {names[edge.source]} -->{label} {names[edge.target]}")
        flowed = {edge.target for edge in spec.edges}
        for node in spec.nodes:
            if node.parent and node.id not in flowed:
                lines.append(f"  {names[node.parent]} -.-> {names[node.id]}")
        lines.extend(["```", "", "| 组件 | 模型 | Prompt |", "| --- | --- | --- |"])
        components = {item for node in spec.nodes for item in _node_components(node)}
        for component_id in sorted(components):
            component = COMPONENTS.get(component_id)
            lines.append(f"| `{component_id}@{component.version}` | `{component.model}` | `{component.prompt.id}` |")
        tool_refs = {
            tool for component_id in components
            for tool in load_definitions().component(component_id)[0].tools
        }
        lines.extend(["", f"工具：{', '.join(f'`{tool}`' for tool in sorted(tool_refs)) or '无'}。", ""])
    lines.append("具体 Prompt 正文：`cd duxue-server && .venv/bin/python -m app.agent_specs show <agent>`。")
    lines.append("")
    return "\n".join(lines)
