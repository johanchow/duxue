"""Authenticated relay from mobile-safe telemetry envelopes to OTLP.

The mobile app must not contain Grafana credentials.  This module creates a
separate provider whose resource is ``service.name=duxue-app`` so relayed data
remains distinguishable from the relay's own ``duxue-server`` request trace.
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from time import monotonic
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

from .schemas import ClientTelemetryEvent

_ALLOWED_NAMES = {
    "app.http", "app.auth.refresh", "app.report.load", "app.device.bind",
    "app.companion.turn", "app.asr.session", "app.screen.load", "app.startup",
    "app.unhandled_error", "app.route.view",
}
_ALLOWED_ATTRIBUTES = {
    "result", "route", "method", "status_class", "screen", "error_kind",
    "platform", "app_version", "network_type", "report_status", "role",
}
_DURATION_METRICS = {"app.screen.load"}
_lock = threading.Lock()
_tracer = None
_meter = None
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}
_rate_windows: dict[str, deque[float]] = defaultdict(deque)


def _enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.getenv("OTEL_SDK_DISABLED", "false").lower() not in {"1", "true", "yes"}


def _providers():
    global _tracer, _meter
    if not _enabled():
        return None, None
    with _lock:
        if _tracer is not None:
            return _tracer, _meter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            SERVICE_NAME: "duxue-app", "service.component": "mobile-client",
            "telemetry.relay": "duxue-server", "deployment.environment.name": os.getenv("APP_ENV", "development"),
        })
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        meter_provider = MeterProvider(metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())], resource=resource)
        _tracer = tracer_provider.get_tracer("duxue.app.relay")
        _meter = meter_provider.get_meter("duxue.app.relay")
        return _tracer, _meter


def _attributes(event: ClientTelemetryEvent) -> dict[str, Any]:
    if event.name not in _ALLOWED_NAMES:
        raise ValueError("unsupported telemetry name")
    if set(event.attributes) - _ALLOWED_ATTRIBUTES:
        raise ValueError("unsupported telemetry attribute")
    attrs = {f"app.{key}": value for key, value in event.attributes.items()}
    # Route values must be pre-normalized templates, not identifiers/query data.
    route = event.attributes.get("route")
    if route is not None and (not isinstance(route, str) or "?" in route or len(route) > 80 or any(part and not part.startswith(":") and len(part) > 24 for part in route.split("/"))):
        raise ValueError("unsafe telemetry route")
    return attrs


def _parent_context(event: ClientTelemetryEvent):
    if not event.trace_id or not event.span_id:
        return None
    parent = SpanContext(
        trace_id=int(event.trace_id, 16), span_id=int(event.span_id, 16),
        is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED), trace_state=TraceState(),
    )
    return trace.set_span_in_context(NonRecordingSpan(parent))


def relay(events: list[ClientTelemetryEvent]) -> int:
    # Validate before checking exporter availability. A disabled exporter must
    # not accidentally turn the authenticated relay into an arbitrary payload
    # sink that accepts private content.
    validated = [(event, _attributes(event)) for event in events]
    tracer, meter = _providers()
    if tracer is None or meter is None:
        return 0
    accepted = 0
    for event, attrs in validated:
        if event.signal == "metric":
            if event.value is None:
                raise ValueError("metric value is required")
            if event.name in _DURATION_METRICS:
                instrument = _histograms.setdefault(event.name, meter.create_histogram(event.name, unit="ms"))
                instrument.record(event.value, attributes=attrs)
            else:
                instrument = _counters.setdefault(event.name, meter.create_counter(event.name, unit="1"))
                instrument.add(event.value, attributes=attrs)
        else:
            counter = _counters.setdefault(event.name, meter.create_counter(event.name, unit="1"))
            counter.add(1, attributes=attrs)
            with tracer.start_as_current_span(event.name, context=_parent_context(event), attributes=attrs) as span:
                if event.duration_ms is not None:
                    span.set_attribute("app.duration_ms", event.duration_ms)
                    histogram = _histograms.setdefault(f"{event.name}.duration", meter.create_histogram(f"{event.name}.duration", unit="ms"))
                    histogram.record(event.duration_ms, attributes=attrs)
                span.add_event("app.telemetry.relayed", {"app.signal": event.signal})
        accepted += 1
    return accepted


def allow_batch(principal_id: str, event_count: int, *, per_minute: int = 120) -> bool:
    """Bound relay cost per authenticated principal without exporting its ID."""
    now = monotonic()
    with _lock:
        window = _rate_windows[principal_id]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) + event_count > per_minute:
            return False
        window.extend([now] * event_count)
        return True
