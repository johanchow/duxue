from __future__ import annotations

from app.infrastructure.observability.telemetry import _should_export_to_langfuse


class _Span:
    def __init__(self, name: str):
        self.name = name


def test_langfuse_export_filter_is_an_explicit_payload_free_allow_list():
    assert _should_export_to_langfuse(_Span("llm.request")) is True
    assert _should_export_to_langfuse(_Span("agent.workflow")) is False
    assert _should_export_to_langfuse(_Span("GET /agent/run")) is False
    assert _should_export_to_langfuse(_Span("SELECT duxue_ward")) is False
