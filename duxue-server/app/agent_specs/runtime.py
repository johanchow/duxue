"""Bind reviewed Python handlers to a declarative workflow topology."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import dataclass

from langgraph.graph import END, START

from app.agent_specs.catalog import AgentSpec, executing_node
from app.agent_specs.execution_trace import record_workflow_execution


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reason_code: str

    def __post_init__(self):
        from app.agent_specs.verdicts import GateVerdict
        GateVerdict(verdict=self.verdict, reason_code=self.reason_code)


@record_workflow_execution
def execute_tutoring_child(node_id: str, **kwargs):
    """Resolve the child against the pinned catalog, including pre-subworkflow snapshots."""
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.execution_trace import recorder
    from app.agent_specs.subworkflows import CALL_TARGETS, RETRY_NODE
    from app.infrastructure.observability.telemetry import agent_step_span

    catalog = load_catalog()
    tutor = catalog.spec("tutoring")
    if tutor.node(RETRY_NODE).kind != "workflow":
        return execute_workflow(catalog.spec(CALL_TARGETS[node_id]), **kwargs)
    node = tutor.node(node_id)
    child = catalog.spec(node.ref)
    recording = recorder()
    if recording and recording.stack and recording.stack[-1].get("node_id") == node_id:
        return execute_workflow(child, **kwargs)
    with agent_step_span(node.trace_kind or "node", node.trace):
        return execute_workflow(child, **kwargs)


@record_workflow_execution
def execute_workflow(
    spec: AgentSpec, *, handlers: dict[str, Callable[[dict], object]],
    conditions: dict[str, Callable[[dict], bool]] | None = None,
    initial_state: dict | None = None,
    entry_node: str | None = None,
    pause_before: set[str] | None = None,
    parallel_runner: Callable | None = None,
) -> dict:
    """Run reviewed nodes and conditions; no expression or import comes from JSON.

    Handlers own authorization, domain writes and transactions. A missing or
    ambiguous edge, unknown Gate result or exhausted step budget fails closed.
    """
    state = dict(initial_state or {})
    state["results"] = {}
    state["visited_gates"] = []
    predicates = conditions or {}
    active_nodes = set()
    frontier = [entry_node or spec.entry]
    while frontier:
        key = frontier.pop()
        if key == 'END' or key in active_nodes or key in (pause_before or set()): continue
        spec.node(key)
        active_nodes.add(key)
        frontier.extend(edge.target for edge in spec.edges if edge.source == key)
    for node in spec.nodes:
        if node.id not in active_nodes: continue
        handler_id = node.ref if node.kind in {"agent", "gate"} else node.handler
        if node.id not in handlers and (not handler_id or handler_id not in handlers):
            raise ValueError(f"{spec.id}: missing handler for {node.id}")
    referenced_conditions = {edge.condition for edge in spec.edges if edge.condition}
    referenced_conditions.update(gate["when"] for gate in spec.required_gates)
    if referenced_conditions - predicates.keys():
        raise ValueError(f"{spec.id}: unknown conditions {sorted(referenced_conditions - predicates.keys())}")
    def _run_node(node_id: str):
        node = spec.node(node_id)
        handler_id = node.ref if node.kind in {"agent", "gate"} else node.handler
        handler = handlers.get(node.id) if node.id in handlers else (handlers.get(handler_id) if handler_id else None)
        if handler is None:
            raise ValueError(f"{spec.id}: missing handler for {node_id}")
        from app.agent_specs.execution_trace import payload, recorder

        current_trace = recorder()
        context = (
            current_trace.step(kind=node.kind, node_id=node_id, workflow_id=spec.id, input=state)
            if current_trace
            else nullcontext(None)
        )
        with context as event:
            token = executing_node.set((spec.id, node_id))
            try:
                result = handler(state)
            finally:
                executing_node.reset(token)
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
            if node.kind == "gate":
                if not isinstance(result, GateDecision) or result.verdict not in {"allow", "deny", "unknown"}:
                    raise ValueError(f"{spec.id}: invalid Gate verdict {node_id}")
                if result.verdict == "unknown":
                    raise ValueError(f"{spec.id}: Gate {node_id} returned unknown")
            if event is not None:
                event["output"] = payload(result)
        return node, result

    current = entry_node or "START"
    for _ in range(32):
        if current in (pause_before or set()):
            state['continuation'] = current
            from app.agent_specs.execution_trace import recorder
            trace = recorder()
            if trace:
                with trace.step(kind='continuation', node_id=current, workflow_id=spec.id): pass
            return state
        if current == "END":
            for gate in spec.required_gates:
                when = gate["when"]
                if when not in predicates:
                    raise ValueError(f"{spec.id}: unknown Gate condition {when}")
                if predicates[when](state) and gate["ref"] not in state["visited_gates"]:
                    raise ValueError(f"{spec.id}: required Gate {gate['ref']} was skipped")
            return state
        if current != "START":
            node, result = _run_node(current)
            state["results"][current] = result
            if node.kind == "gate":
                state["visited_gates"].append(node.ref)
        matching = []
        for edge in spec.edges:
            if edge.source != current:
                continue
            if edge.condition and edge.condition not in predicates:
                raise ValueError(f"{spec.id}: unknown condition {edge.condition}")
            selected = edge.condition is None or bool(predicates[edge.condition](state))
            from app.agent_specs.execution_trace import record_edge
            record_edge(spec, edge, selected=selected, value=selected if edge.condition else None, input=state)
            if selected:
                matching.append(edge)
        if len(matching) == 1:
            current = matching[0].target
            continue
        if len(matching) > 1:
            targets = [edge.target for edge in matching]
            join_targets = set()
            for target in targets:
                out_edges = [edge for edge in spec.edges if edge.source == target]
                if len(out_edges) != 1 or out_edges[0].condition is not None:
                    raise ValueError(f"{spec.id}: parallel branch {target} must converge unconditionally")
                join_targets.add(out_edges[0].target)
            if len(join_targets) != 1:
                raise ValueError(f"{spec.id}: parallel branches from {current} do not converge to one join node")
            join_node = next(iter(join_targets))
            if parallel_runner:
                branch_results = parallel_runner(targets, _run_node)
            else:
                from app.agent_specs.execution_trace import Recorder, recorder

                parent = recorder()
                children = {target: Recorder() for target in targets} if parent is not None else {}

                def _run_branch(target_id: str):
                    capture = children[target_id].capture() if parent is not None else nullcontext()
                    with capture:
                        return _run_node(target_id)

                with ThreadPoolExecutor(max_workers=len(targets)) as pool:
                    futures = {
                        target: pool.submit(copy_context().run, _run_branch, target)
                        for target in targets
                    }
                    branch_results = {}
                    for target in targets:
                        branch_results[target] = futures[target].result()
                        if parent is not None:
                            parent.merge_child(children[target])
            for target, (branch_node, branch_result) in branch_results.items():
                state["results"][target] = branch_result
                if branch_node.kind == "gate":
                    state["visited_gates"].append(branch_node.ref)
            from app.agent_specs.execution_trace import record_edge
            for target in targets:
                join_edge = next(edge for edge in spec.edges if edge.source == target and edge.target == join_node)
                record_edge(spec, join_edge, selected=True, value=None, input=state)
            current = join_node
            continue
        raise ValueError(f"{spec.id}: expected one edge from {current}, got {len(matching)}")
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
