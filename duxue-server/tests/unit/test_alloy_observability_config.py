from __future__ import annotations

from types import SimpleNamespace

from app.infrastructure.observability.telemetry import _should_export_to_langfuse


class _Span:
    def __init__(self, name: str, scope: str | None = None):
        self.name = name
        self.instrumentation_scope = SimpleNamespace(name=scope or ("duxue.model" if name == "llm.request" else "duxue.agent"))


def test_langfuse_export_filter_is_an_explicit_payload_free_allow_list():
    for name in ("agent.turn", "agent.route", "agent.workflow", "agent.node", "agent.tool", "agent.check", "llm.request", "planning.graph_invoke"):
        assert _should_export_to_langfuse(_Span(name)) is True
    assert _should_export_to_langfuse(_Span("planning.unregistered")) is False
    assert _should_export_to_langfuse(_Span("agent.workflow", scope="untrusted.integration")) is False
    assert _should_export_to_langfuse(_Span("llm.request", scope="untrusted.integration")) is False
    assert _should_export_to_langfuse(_Span("GET /agent/run")) is False
    assert _should_export_to_langfuse(_Span("SELECT duxue_ward")) is False
