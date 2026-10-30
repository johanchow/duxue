"""Bind reviewed Python handlers to a declarative workflow topology."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph import END, START

from app.agent_specs.catalog import AgentSpec


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reason_code: str

    def __post_init__(self):
        from app.agent_specs.verdicts import GateVerdict
        GateVerdict(verdict=self.verdict, reason_code=self.reason_code)


def execute_workflow(
    spec: AgentSpec, *, handlers: dict[str, Callable[[dict], object]],
    conditions: dict[str, Callable[[dict], bool]] | None = None,
    initial_state: dict | None = None,
) -> dict:
    """Run reviewed nodes and conditions; no expression or import comes from JSON.

    Handlers own authorization, domain writes and transactions. A missing or
    ambiguous edge, unknown Gate result or exhausted step budget fails closed.
    """
    state = dict(initial_state or {})
    state["results"] = {}
    state["visited_gates"] = []
    predicates = conditions or {}
    for node in spec.nodes:
        handler_id = node.ref if node.kind in {"agent", "gate"} else node.handler
        if not handler_id or handler_id not in handlers:
            raise ValueError(f"{spec.id}: missing handler for {node.id}")
    referenced_conditions = {edge.condition for edge in spec.edges if edge.condition}
    referenced_conditions.update(gate["when"] for gate in spec.required_gates)
    if referenced_conditions - predicates.keys():
        raise ValueError(f"{spec.id}: unknown conditions {sorted(referenced_conditions - predicates.keys())}")
    current = "START"
    for _ in range(32):
        if current == "END":
            for gate in spec.required_gates:
                when = gate["when"]
                if when not in predicates:
                    raise ValueError(f"{spec.id}: unknown Gate condition {when}")
                if predicates[when](state) and gate["ref"] not in state["visited_gates"]:
                    raise ValueError(f"{spec.id}: required Gate {gate['ref']} was skipped")
            return state
        if current != "START":
            node = spec.node(current)
            handler_id = node.ref if node.kind in {"agent", "gate"} else node.handler
            if not handler_id or handler_id not in handlers:
                raise ValueError(f"{spec.id}: missing handler for {current}")
            result = handlers[handler_id](state)
            if node.kind == "agent":
                from app.agent_specs.results import (
                    AgentResult,
                    completed,
                    validate_result,
                )
                if not isinstance(result, AgentResult):
                    data = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                    result = completed(data if data is not None else {})
                result = validate_result(result)
            state["results"][current] = result
            if node.kind == "gate":
                if not isinstance(result, GateDecision) or result.verdict not in {"allow", "deny", "unknown"}:
                    raise ValueError(f"{spec.id}: invalid Gate verdict {current}")
                if result.verdict == "unknown":
                    raise ValueError(f"{spec.id}: Gate {current} returned unknown")
                state["visited_gates"].append(node.ref)
        matching = []
        for edge in spec.edges:
            if edge.source != current:
                continue
            if edge.condition is None or edge.condition in predicates and predicates[edge.condition](state):
                matching.append(edge)
            elif edge.condition not in predicates:
                raise ValueError(f"{spec.id}: unknown condition {edge.condition}")
        if len(matching) != 1:
            raise ValueError(f"{spec.id}: expected one edge from {current}, got {len(matching)}")
        current = matching[0].target
    raise ValueError(f"{spec.id}: step budget exhausted")


def wire_langgraph(graph, spec: AgentSpec, *, handlers: dict[str, object],
                   routers: dict[str, object]) -> None:
    """Use the spec's edges while handlers keep domain behavior in Python."""
    graph_nodes = {node.id: node for node in spec.nodes if node.graph_key}
    from app.agent_specs.definitions import load_definitions

    def handler_id(node):
        return load_definitions().code_gates[node.ref].handler_id if node.kind == "gate" else node.handler

    if any(handler_id(node) is None for node in graph_nodes.values()):
        raise ValueError(f"{spec.id}: graph node missing handler")
    if set(handlers) != {handler_id(node) for node in graph_nodes.values()}:
        raise ValueError(f"{spec.id}: graph handlers differ from declared nodes")
    referenced_routers = {edge.via for edge in spec.edges if edge.via}
    router_handlers = {spec.node(node_id).handler for node_id in referenced_routers}
    if None in router_handlers or set(routers) != router_handlers:
        raise ValueError(f"{spec.id}: graph routers differ from declared nodes")
    for node in spec.nodes:
        if node.graph_key:
            graph.add_node(node.graph_key, handlers[handler_id(node)])

    def graph_key(node_id: str):
        if node_id == "START":
            return START
        if node_id == "END":
            return END
        try:
            return graph_nodes[node_id].graph_key
        except KeyError as error:
            raise ValueError(f"{spec.id}: {node_id} is not a graph node") from error

    conditional = defaultdict(dict)
    for edge in spec.edges:
        if edge.condition:
            if edge.via is None:
                raise ValueError(f"{spec.id}: conditional edge needs a router")
            conditional[edge.source, edge.via][edge.condition] = graph_key(edge.target)
        else:
            if edge.via:
                raise ValueError(f"{spec.id}: router on unconditional edge")
            graph.add_edge(graph_key(edge.source), graph_key(edge.target))
    for (source, via), choices in conditional.items():
        graph.add_conditional_edges(graph_key(source), routers[spec.node(via).handler], choices)
