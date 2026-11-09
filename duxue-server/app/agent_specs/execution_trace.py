"""Optional, request-local execution evidence. Inactive during normal service calls."""

from __future__ import annotations

import dataclasses
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from enum import Enum
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
        return value[:20000]
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
            if k not in {"password", "password_hash", "api_key", "token"}
        }
    if isinstance(value, (list, tuple, set)):
        return [payload(v, depth + 1) for v in list(value)[:100]]
    return {"type": type(value).__name__}


class Recorder:
    def __init__(self):
        self.events = []
        self.stack = []
        self.spans = {}

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
            self.stack.pop()


def recorder():
    return _current.get()


@contextmanager
def observe_span(identity, span):
    current = recorder()
    if current is None:
        yield
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


def record_edge(spec, edge, *, selected, value=None):
    current = recorder()
    if current:
        current.events.append(
            {
                "id": str(len(current.events) + 1),
                "kind": "edge",
                "workflow_id": spec.id,
                "from": edge.source,
                "to": edge.target,
                "condition_id": edge.condition,
                "selected": selected,
                "condition_result": value,
                "status": "evaluated",
            }
        )


def transition(workflow_id, source, target, condition=None):
    """Record a code-owned branch where it actually occurs, without re-evaluating policy."""
    if recorder() is None:
        return
    from app.agent_specs.catalog import load_catalog

    spec = load_catalog().spec(workflow_id)
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
