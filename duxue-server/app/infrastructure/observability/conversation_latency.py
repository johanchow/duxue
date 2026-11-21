"""Export a mobile completion at its original timestamp, including on retry."""
import json
import os

from opentelemetry._logs import LogRecord
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import LogRecordExportResult
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from app.api.schemas import ClientTelemetryEvent

EVENT = "app.conversation.completed"


def completion_record(event: ClientTelemetryEvent) -> ReadableLogRecord:
    if (event.signal != "event" or event.turn_id is None or event.duration_ms is None
            or event.completed_ms is None or event.span_id or event.value is not None
            or set(event.attributes) != {"role", "result"}
            or event.attributes["role"] not in ("guardian", "ward")
            or event.attributes["result"] not in ("success", "timeout", "cancelled", "error")):
        raise ValueError("invalid conversation completion")
    payload = {
        "event": EVENT, "turn_id": event.turn_id, "completed_ms": event.completed_ms,
        "duration_ms": event.duration_ms, "entry": event.attributes["role"],
        "result": event.attributes["result"],
    }
    if event.trace_id:
        payload["server_trace"] = event.trace_id
    timestamp = event.completed_ms * 1_000_000
    return ReadableLogRecord(
        log_record=LogRecord(context=Context(), timestamp=timestamp, observed_timestamp=timestamp,
                             body=json.dumps(payload, separators=(",", ":"))),
        resource=Resource({"service.name": "duxue-app", "deployment.environment.name":
                           os.getenv("APP_ENV", "development")}),
        instrumentation_scope=InstrumentationScope("duxue.app.conversation"),
    )


def export_completions(records: list[ReadableLogRecord]) -> bool:
    exporter = OTLPLogExporter(timeout=5)
    try:
        return exporter.export(records) == LogRecordExportResult.SUCCESS
    finally:
        exporter.shutdown()
