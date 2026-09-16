from __future__ import annotations

import pytest

from app.infrastructure.observability.client_telemetry import _attributes
from app.api.schemas import ClientTelemetryEvent


def event(**overrides) -> ClientTelemetryEvent:
    payload = {
        "signal": "span",
        "name": "app.http",
        "duration_ms": 12,
        "attributes": {"result": "success", "route": "/wards/:id/report"},
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
    }
    payload.update(overrides)
    return ClientTelemetryEvent(**payload)


def test_client_telemetry_preserves_only_allowlisted_low_cardinality_attributes():
    attrs = _attributes(event())
    assert attrs == {"app.result": "success", "app.route": "/wards/:id/report"}


def test_client_telemetry_accepts_anonymized_asr_outcome():
    # Must match Flutter AppTelemetry / VoiceTranscriptionService name.
    assert _attributes(event(
        name="app.asr.session",
        attributes={"result": "error", "error_kind": "auth", "route": "/ws/asr/transcribe"},
    )) == {
        "app.result": "error",
        "app.error_kind": "auth",
        "app.route": "/ws/asr/transcribe",
    }


@pytest.mark.parametrize("attributes", [
    {"content": "child private text"},
    {"ward_id": "ward-secret"},
    {"route": "/wards/a-very-long-identifier-that-must-not-be-exported"},
    {"route": "/reports?ward_id=ward-secret"},
])
def test_client_telemetry_rejects_sensitive_or_untemplated_attributes(attributes):
    with pytest.raises(ValueError):
        _attributes(event(attributes=attributes))


def test_client_telemetry_contract_rejects_non_w3c_trace_ids():
    with pytest.raises(ValueError):
        event(trace_id="not-a-trace")
