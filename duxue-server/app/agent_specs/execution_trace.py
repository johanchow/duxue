"""Request-local execution evidence shared by debugging, evals and sampled tracing."""

from __future__ import annotations

import dataclasses
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from enum import Enum
from functools import wraps
from uuid import UUID

_current = ContextVar("agent_debug_trace", default=None)


def payload(value, depth=0):
    if depth > 12:
        return {"truncated": True}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return "[image bytes omitted]"
        return value if len(value) <= 20000 else {"truncated": True, "preview": value[:20000], "original_length": len(value)}
    if isinstance(value, (date, datetime, UUID, Enum)):
        return str(value)
    if hasattr(value, "model_dump"):
        return payload(value.model_dump(mode="json"), depth + 1)
    if dataclasses.is_dataclass(value):
        return {
            f.name: payload(getattr(value, f.name), depth + 1)
            for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {
            str(k): payload(v, depth + 1)
            for k, v in value.items()
            if str(k).lower() not in {"password", "password_hash", "api_key", "token", "secret_key", "authorization", "access_token", "refresh_token"}
        }
    if isinstance(value, (list, tuple, set)):
        return [payload(v, depth + 1) for v in list(value)[:100]]
    return {"type": type(value).__name__}


class Recorder:
    def __init__(self):
        self.events = []
        self.stack = []
        self.spans = {}

    def merge_child(self, child):
        """Attach a completed parallel branch without sharing live event stacks."""
        offset = len(self.events)
        parent_id = self.stack[-1]["id"] if self.stack else None
        for event in child.events:
            self.events.append({
                **event,
                "id": str(offset + int(event["id"])),
                "parent_id": str(offset + int(event["parent_id"])) if event["parent_id"] else parent_id,
            })

    def timings(self):
        """Return completed visits with timing metadata and no request/response bodies."""
        fields = (
            "id", "parent_id", "kind", "workflow_id", "node_id", "component_id", "model",
            "started_at", "duration_ms", "first_token_ms", "first_content_ms", "status",
            "outcome", "finish_reason", "tokens_in", "tokens_out", "tokens_reasoning", "tokens_answer", "reasoning_effort", "error",
        )
        return [
            {key: event[key] for key in fields if key in event}
            for event in self.events if "duration_ms" in event
        ]

    def document(self):
        """Freeze executed topology from the active immutable configuration."""
        from app.agent_specs.catalog import load_catalog
        from app.agent_specs.definitions import load_definitions

        catalog, definitions = load_catalog(), load_definitions()
        ids = {e.get("workflow_id") for e in self.events}
        # Freeze referenced children even when a conditional call did not execute.
        pending = list(ids.intersection(catalog.specs))
        while pending:
            for node in catalog.spec(pending.pop()).nodes:
                if node.kind == "workflow" and node.ref not in ids:
                    ids.add(node.ref)
                    pending.append(node.ref)
        flows = {key: spec.model_dump(mode="json", by_alias=True)
                 for key, spec in catalog.specs.items() if key in ids}
        units = {**definitions.units, **definitions.code_agents,
                 **definitions.code_gates, **definitions.tools}
        refs = {n.get("ref") for f in flows.values() for n in f["nodes"]}
        return {"schema_version": "duxue-execution.v1", "events": self.events,
                "catalog": {"source": "execution-snapshot", "workflows": flows, "definitions": {
                    key: {"id": key, "kind": unit.kind,
                          "implementation": getattr(unit, "implementation", "code"),
                          "display_name": getattr(unit, "display_name", None)}
                    for key, unit in units.items() if key in refs}},
                "capture": "recorded_events_only"}

    @contextmanager
    def capture(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    @contextmanager
    def step(self, *, kind, node_id, workflow_id=None, input=None, **extra):
        event = {
            "id": str(len(self.events) + 1),
            "parent_id": self.stack[-1]["id"] if self.stack else None,
            "kind": kind,
            "node_id": node_id,
            "workflow_id": workflow_id,
            "input": payload(input),
            "status": "running",
            "started_at": datetime.now().astimezone().isoformat(),
            **extra,
        }
        self.events.append(event)
        self.stack.append(event)
        started = time.monotonic()
        try:
            yield event
            event["status"] = "succeeded"
        except Exception as error:
            event.update(status="failed", error=type(error).__name__)
            raise
        finally:
            event["duration_ms"] = round((time.monotonic() - started) * 1000)
            event["ended_at"] = datetime.now().astimezone().isoformat()
            self.stack.pop()


def recorder():
    return _current.get()


def record_workflow_execution(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from app.infrastructure.observability.telemetry import (
            _agent_context_attrs,
            _langfuse_enabled,
        )
        if recorder() is not None or not _langfuse_enabled():
            return function(*args, **kwargs)
        from opentelemetry import trace
        recording = Recorder()
        with trace.get_tracer("duxue.agent").start_as_current_span(
            "agent.execution", record_exception=False, set_status_on_exception=False,
            attributes={"langfuse.observation.type": "span", **_agent_context_attrs()},
        ) as span:
            if not span.is_recording():
                return function(*args, **kwargs)
            with recording.capture():
                try:
                    return function(*args, **kwargs)
                finally:
                    from app.infrastructure.observability.telemetry import (
                        set_observation_payload,
                    )
                    set_observation_payload(span, output=recording.document())
    return wrapped


@contextmanager
def observe_span(identity, span):
    current = recorder()
    if current is None:
        yield
        return
    from app.agent_specs.catalog import executing_node, load_catalog
    active = executing_node.get()
    spec = load_catalog().spec(identity.owner)
    if spec.execution and active is None and identity.node_id == spec.entry:
        # The entry-point span covers the whole invocation; the runner records the entry node.
        yield
        return
    if spec.execution and active and active[0] == identity.owner:
        if any(edge.source == identity.node_id for edge in spec.edges):
            # The runner already owns this visit. Keep the OTEL span and attach
            # domain payloads to the actual operation, even for result projection.
            event = current.stack[-1] if current.stack else None
            if event is not None:
                current.spans.setdefault(id(span), []).append(event)
            try:
                yield
            finally:
                if event is not None:
                    current.spans[id(span)].pop()
            return
    with current.step(
        kind=identity.unit_kind,
        node_id=identity.node_id,
        workflow_id=identity.owner,
        unit_id=identity.unit_id,
    ) as event:
        # No-op OTEL uses a shared NonRecordingSpan: retain nested bindings as a stack.
        current.spans.setdefault(id(span), []).append(event)
        try:
            yield
        finally:
            current.spans[id(span)].pop()


def observe_payload(span, *, input=None, output=None):
    current = recorder()
    events = current.spans.get(id(span), []) if current else []
    if events:
        if input is not None:
            events[-1]["input"] = payload(input)
        if output is not None:
            events[-1]["output"] = payload(output)


@contextmanager
def observe_model(component_id, span, *, input=None, model=None):
    current = recorder()
    if current is None:
        yield None
        return
    from app.agent_specs.catalog import load_catalog

    identity = load_catalog().component_identity(component_id) if component_id else None
    # Isolated debug already wraps the component with a model event.
    if current.stack and current.stack[-1].get("component_id") == component_id:
        yield current.stack[-1]
        return
    with current.step(kind="model", node_id=identity.node_id if identity else None,
                      workflow_id=identity.owner if identity else None,
                      unit_id=identity.unit_id if identity else None,
                      component_id=component_id, model=model, input=input) as event:
        current.spans.setdefault(id(span), []).append(event)
        try:
            yield event
        finally:
            current.spans[id(span)].pop()


def record_edge(spec, edge, *, selected, value=None, input=None):
    current = recorder()
    if current:
        current.events.append(
            {
                "id": str(len(current.events) + 1),
                "kind": "edge",
                "parent_id": current.stack[-1]["id"] if current.stack else None,
                "workflow_id": spec.id,
                "from": edge.source,
                "to": edge.target,
                "condition_id": edge.condition,
                "selected": selected,
                "condition_result": value,
                "input": payload(input),
                "status": "evaluated",
            }
        )


def transition(workflow_id, source, target, condition=None):
    """Record a code-owned branch where it actually occurs, without re-evaluating policy."""
    if recorder() is None:
        return
    from app.agent_specs.catalog import load_catalog

    spec = load_catalog().spec(workflow_id)
    if spec.execution:
        return  # The runner records selected and unselected edges itself.
    edge = next(
        (
            e
            for e in spec.edges
            if e.source == source and e.target == target and e.condition == condition
        ),
        None,
    )
    if edge is not None:
        record_edge(spec, edge, selected=True, value=True if condition else None)
