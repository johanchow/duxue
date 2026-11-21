from __future__ import annotations

from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_ward


def _payload():
    return {
        "events": [{
            "signal": "span", "name": "app.http", "duration_ms": 12,
            "attributes": {"result": "success", "route": "/wards/:id/report"},
            "trace_id": "a" * 32, "span_id": "b" * 16,
        }]
    }


def test_mobile_telemetry_relay_requires_existing_short_lived_login(client):
    response = client.post("/telemetry/client-events", json=_payload())
    assert response.status_code == 401


def test_mobile_telemetry_relay_accepts_ward_context_without_exporting_identity(client, db, monkeypatch):
    ward = create_ward(db)
    db.commit()
    monkeypatch.setattr("app.api.v1.system.relay_client_telemetry", lambda events: len(events))
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)

    response = client.post(
        "/telemetry/client-events", json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 1}


def test_mobile_telemetry_relay_rejects_private_content_even_when_authenticated(client, db):
    ward = create_ward(db)
    db.commit()
    token = create_access_token(user_id=ward.id, role="ward", ward_session_version=1)
    payload = _payload()
    payload["events"][0]["attributes"] = {"content": "child private text"}

    response = client.post(
        "/telemetry/client-events", json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


def test_turn_completion_retries_preserve_time_identity_and_long_tail(monkeypatch):
    from app.api.schemas import ClientTelemetryEvent
    from app.infrastructure.observability import client_telemetry, conversation_latency

    event = ClientTelemetryEvent(signal="event", name=conversation_latency.EVENT,
                                duration_ms=181_859, completed_ms=1_795_222_200_000,
                                turn_id="f" * 32, attributes={"role": "guardian", "result": "success"})
    records = []
    monkeypatch.setattr(client_telemetry, "_enabled", lambda: True)
    monkeypatch.setattr(conversation_latency, "export_completions", lambda batch: not records.extend(batch))
    for _ in range(2):
        assert client_telemetry.relay([event]) == 1
    assert records[0].log_record.body == records[1].log_record.body
    assert records[0].log_record.timestamp == records[1].log_record.timestamp == event.completed_ms * 1_000_000
    monkeypatch.setattr(conversation_latency, "export_completions", lambda batch: False)
    assert client_telemetry.relay([event]) == 0


def test_turn_completion_rejects_invalid_dimensions():
    import pytest

    from app.api.schemas import ClientTelemetryEvent
    from app.infrastructure.observability import client_telemetry

    event = ClientTelemetryEvent(signal="event", name="app.conversation.completed", turn_id="a" * 32,
                                duration_ms=12, completed_ms=1000, attributes={"role": "ward", "result": "secret"})
    with pytest.raises(ValueError, match="invalid conversation completion"):
        client_telemetry.relay([event])


def test_sampled_business_request_can_be_found_even_if_client_times_out(monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from starlette.requests import Request
    from starlette.responses import Response

    from app.api.deps import expose_turn_trace

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    response = Response()
    request = Request({"type": "http", "headers": [(b"x-duxue-turn-id", b"a" * 32)]})
    with provider.get_tracer("test").start_as_current_span("turn"):
        expose_turn_trace(request, response)
        assert response.headers["x-duxue-trace-id"] == trace.format_trace_id(
            trace.get_current_span().get_span_context().trace_id)
    assert sink.get_finished_spans()[0].attributes["app.conversation.turn_id"] == "a" * 32
