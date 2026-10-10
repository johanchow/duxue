"""Privacy-safe OpenTelemetry bootstrap and Duxue business telemetry.

Grafana is for operational health and debugging, never the system of record for
children's conversations.  This module deliberately exposes summaries, hashes
and low-cardinality dimensions only.  Full text is written nowhere unless a
separate, explicitly configured encrypted debug-audit sink is enabled.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from opentelemetry import metrics, trace


_configured = False
_lock = threading.Lock()
_audit_logger = logging.getLogger("duxue.agent.audit")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")


def _enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.getenv("OTEL_SDK_DISABLED", "false").lower() not in {"1", "true", "yes"}


def _component_resource(component: str):
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME

    return Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "duxue-server"),
        "service.component": component,
        "deployment.environment.name": os.getenv("APP_ENV", "development"),
    })


class _TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span_context = trace.get_current_span().get_span_context()
        record.trace_id = format(span_context.trace_id, "032x") if span_context.is_valid else ""
        record.span_id = format(span_context.span_id, "016x") if span_context.is_valid else ""
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "span_id": getattr(record, "span_id", ""),
        }
        if hasattr(record, "telemetry"):
            payload["telemetry"] = record.telemetry
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_observability(*, component: str, app=None, engine=None) -> bool:
    """Configure OTLP once per process; return false when export is disabled.

    OTLP exporters read the standard ``OTEL_EXPORTER_OTLP_*`` variables, so
    Grafana Cloud and Alloy require no source-code-specific credentials.
    """
    global _configured
    if not _enabled():
        return False
    with _lock:
        if _configured:
            return True
        resource = _component_resource(component)
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry import _logs
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(MeterProvider(
            metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())], resource=resource,
        ))
        _register_runtime_gauges(component)

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        _logs.set_logger_provider(logger_provider)

        # OTEL logs are still evolving in Python.  Keep stdout JSON as the
        # dependable container log path, with trace/span IDs for Loki derived
        # fields; OTLP traces and metrics use the configured exporter above.
        root = logging.getLogger()
        if not any(getattr(handler, "_duxue_otel", False) for handler in root.handlers):
            handler = logging.StreamHandler()
            handler._duxue_otel = True  # type: ignore[attr-defined]
            handler.addFilter(_TraceContextFilter())
            handler.setFormatter(_JsonFormatter())
            root.addHandler(handler)
            otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
            otel_handler._duxue_otel_logs = True  # type: ignore[attr-defined]
            root.addHandler(otel_handler)
            root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

        _instrument(component=component, app=app, engine=engine)
        _configured = True
    return True


def _register_runtime_gauges(component: str) -> None:
    """Poll the two durable health sources at export time, not per request."""
    meter = metrics.get_meter("duxue.runtime")
    if component == "api":
        meter.create_observable_gauge(
            "duxue.device.online",
            callbacks=[_observe_online_devices],
            unit="1",
            description="Devices whose last heartbeat is currently online in the database.",
        )
    if component == "worker":
        meter.create_observable_gauge(
            "duxue.celery.queue.depth",
            callbacks=[_observe_celery_queue],
            unit="1",
            description="Approximate pending task count in the default Celery queue.",
        )


def _observe_online_devices(_options):
    try:
        from sqlalchemy import func
        from .database import SessionLocal
        from .models import Device
        with SessionLocal() as db:
            count = db.query(func.count(Device.id)).filter(Device.status == "online").scalar() or 0
        return [metrics.Observation(count)]
    except Exception:
        return []


def _observe_celery_queue(_options):
    try:
        import redis
        from .config import settings
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        # Celery's default Redis transport queue key is `celery`; a custom
        # queue still has full task traces, while this gauge remains absent.
        return [metrics.Observation(client.llen("celery"), {"celery.queue": "celery"})]
    except Exception:
        return []


def _instrument(*, component: str, app=None, engine=None) -> None:
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument(engine=engine)
    if component in {"worker", "beat"}:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        CeleryInstrumentor().instrument()
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
    except Exception:
        pass
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except ImportError:
        # The package is a production requirement.  This keeps an older local
        # virtualenv usable until dependencies are refreshed.
        pass


def _meter():
    return metrics.get_meter("duxue.observability")


_agent_turns = _meter().create_counter("duxue.agent.turns", unit="1")
_agent_routes = _meter().create_counter("duxue.agent.routes", unit="1")
_agent_duration = _meter().create_histogram("duxue.agent.run.duration", unit="ms")
_llm_requests = _meter().create_counter("duxue.llm.requests", unit="1")
_llm_duration = _meter().create_histogram("duxue.llm.duration", unit="ms")
_llm_tokens = _meter().create_counter("duxue.llm.tokens", unit="1")
_llm_fallbacks = _meter().create_counter("duxue.llm.fallbacks", unit="1")
_vlm_frames = _meter().create_counter("duxue.vlm.frames.analyzed", unit="1")
_batch_fallbacks = _meter().create_counter("duxue.batch.fallbacks", unit="1")
_batch_total = _meter().create_counter("duxue.batch.total", unit="1")
_frames = _meter().create_counter("duxue.capture.frames", unit="1")
_celery_tasks = _meter().create_counter("duxue.celery.tasks", unit="1")
_celery_duration = _meter().create_histogram("duxue.celery.task.duration", unit="ms")
_asr_sessions = _meter().create_counter("duxue.asr.sessions", unit="1")


def _summary(value: str | None) -> dict[str, Any]:
    text = value or ""
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "length": len(text)}


def _attrs(**attrs: Any) -> dict[str, Any]:
    return {key: value for key, value in attrs.items() if value is not None}


def _span_event(name: str, attributes: dict[str, Any]) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.add_event(name, attributes=attributes)


def record_agent_input(*, agent_type: str, run_id: str | None, thread_id: str | None, content: str) -> None:
    summary = _summary(content)
    attrs = _attrs(**{"agent.type": agent_type, "agent.run_id": run_id, "agent.thread_id": thread_id, "input.length": summary["length"]})
    _span_event("agent.turn.received", attrs)
    _audit_logger.info("agent.turn.received", extra={"telemetry": {**attrs, "input.sha256": summary["sha256"]}})
    _write_debug_audit("input", {**attrs, "input": summary}, content)


def record_agent_route(*, target: str, mode: str, reason: str) -> None:
    attrs = {"agent.target": target, "agent.mode": mode, "agent.route_reason": reason}
    _agent_routes.add(1, attributes={"agent.target": target, "agent.mode": mode})
    _span_event("agent.route.decided", attrs)


def record_agent_outcome(*, agent_type: str, status: str, duration_ms: int, fallback: bool = False) -> None:
    attrs = {"agent.type": agent_type, "agent.status": status}
    _agent_turns.add(1, attributes=attrs)
    _agent_duration.record(duration_ms, attributes=attrs)
    _span_event("agent.workflow.completed", {**attrs, "agent.duration_ms": duration_ms, "agent.fallback": fallback})


def record_companion_rejection(*, code: str, status_code: int, has_thread: bool,
                               has_structured_command: bool) -> None:
    """Audit a rejected companion turn without recording Ward text or IDs."""
    attrs = {
        "companion.rejection_code": code,
        "http.status_code": status_code,
        "companion.has_thread": has_thread,
        "companion.has_structured_command": has_structured_command,
    }
    _span_event("companion.turn.rejected", attrs)
    _audit_logger.warning("companion.turn.rejected", extra={"telemetry": attrs})


_CLOCK_VALUE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def _planning_value_shape(value: Any) -> str:
    """Classify a rejected planning value without retaining the value itself."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "empty"
    if not isinstance(value, str):
        return "other"
    text = value.strip()
    if not text:
        return "empty"
    if _CLOCK_VALUE.fullmatch(text):
        return "clock"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return "text"
    return "iso"


def record_planning_input_rejected(*, field: str, code: str, value: Any) -> None:
    """Audit why a planning answer was refused, keeping only a low-cardinality shape."""
    attrs = {
        "planning.field": field,
        "planning.rejection_code": code,
        "planning.value_shape": _planning_value_shape(value),
        "http.status_code": 400,
    }
    _span_event("planning.input.rejected", attrs)
    _audit_logger.warning("planning.input.rejected", extra={"telemetry": attrs})


def record_planning_stage(*, stage: str, duration_ms: int | None = None, **extra: Any) -> None:
    """Low-cardinality planning lifecycle breadcrumbs for locating post-LLM hangs."""
    attrs = _attrs(**{"agent.type": "planning", "planning.stage": stage, "planning.duration_ms": duration_ms, **extra})
    _span_event(f"planning.stage.{stage}", attrs)
    _audit_logger.info("planning.stage", extra={"telemetry": attrs})


@contextmanager
def planning_stage_span(stage: str, **extra: Any) -> Iterator[None]:
    started = perf_counter()
    with trace.get_tracer("duxue.agent").start_as_current_span(
        f"planning.{stage}",
        attributes=_attrs(**{"agent.type": "planning", "planning.stage": stage, **extra}),
    ):
        try:
            yield
        finally:
            record_planning_stage(stage=stage, duration_ms=round((perf_counter() - started) * 1000), **extra)


@contextmanager
def agent_workflow_span(*, agent_type: str, run_id: str, thread_id: str) -> Iterator[None]:
    with trace.get_tracer("duxue.agent").start_as_current_span(
        "agent.workflow",
        attributes={"agent.type": agent_type, "agent.run_id": run_id, "agent.thread_id": thread_id},
    ):
        yield


@contextmanager
def model_call_span(*, operation: str, model: str, agent_type: str | None = None) -> Iterator[dict[str, Any]]:
    started = perf_counter()
    attrs = _attrs(**{"llm.operation": operation, "llm.model": model, "agent.type": agent_type})
    with trace.get_tracer("duxue.model").start_as_current_span("llm.request", attributes=attrs) as span:
        result: dict[str, Any] = {"result": "success", "tokens_in": None, "tokens_out": None, "provider_request_id": None}
        try:
            yield result
        except Exception as error:
            result["result"] = "error"
            span.record_exception(error)
            span.set_status(trace.Status(trace.StatusCode.ERROR, type(error).__name__))
            raise
        finally:
            duration_ms = round((perf_counter() - started) * 1000)
            attrs_with_result = {**attrs, "llm.result": result["result"]}
            _llm_requests.add(1, attributes=attrs_with_result)
            _llm_duration.record(duration_ms, attributes=attrs_with_result)
            if result["tokens_in"] is not None:
                _llm_tokens.add(result["tokens_in"], attributes={**attrs, "llm.direction": "input"})
            if result["tokens_out"] is not None:
                _llm_tokens.add(result["tokens_out"], attributes={**attrs, "llm.direction": "output"})
            for key in ("provider_request_id", "tokens_in", "tokens_out"):
                if result[key] is not None:
                    span.set_attribute(f"llm.{key}", result[key])
            span.set_attribute("llm.duration_ms", duration_ms)


def record_plan_intake_structure(
    *, has_image: bool, operation_count: int, slot_update_count: int, clarification_required: bool,
    recent_utterance_count: int = 0,
) -> None:
    """Record how many structured proposals the intake model returned, never their text."""
    attrs = _attrs(**{
        "llm.operation": "plan_intake",
        "plan_intake.has_image": has_image,
        "plan_intake.operation_count": operation_count,
        "plan_intake.slot_update_count": slot_update_count,
        "plan_intake.clarification_required": clarification_required,
        "plan_intake.recent_utterance_count": recent_utterance_count,
    })
    _span_event("plan_intake.structured", attrs)
    _audit_logger.info("plan_intake.structured", extra={"telemetry": attrs})


def record_planning_loop_outcome(*, status: str, has_image: bool) -> None:
    """Record the deterministic planning loop status after intake is applied."""
    attrs = _attrs(**{
        "llm.operation": "plan_intake",
        "plan_intake.has_image": has_image,
        "planning.loop_status": status,
    })
    _span_event("planning.loop", attrs)
    _audit_logger.info("planning.loop", extra={"telemetry": attrs})


def record_model_response(*, agent_type: str, model: str, content: str, operation: str | None = None) -> None:
    """Record one model completion. Stdout and Grafana stay content-free; the original text goes to the local audit file."""
    summary = _summary(content)
    attrs = _attrs(**{
        "agent.type": agent_type,
        "llm.model": model,
        "llm.operation": operation,
        "output.length": summary["length"],
        "output.sha256": summary["sha256"],
    })
    _span_event("llm.response.validated", attrs)
    _audit_logger.info("llm.response.validated", extra={"telemetry": attrs})
    _write_debug_audit("output", {"agent.type": agent_type, "llm.model": model, "llm.operation": operation, "output": summary}, content)


def record_llm_fallback(*, operation: str, reason: str) -> None:
    _llm_fallbacks.add(1, attributes={"llm.operation": operation, "fallback.reason": reason})
    _span_event("llm.fallback", {"llm.operation": operation, "fallback.reason": reason})


def record_tutor_candidate_rejection(*, error_type: str, field: str, retrying: bool) -> None:
    """Expose schema drift without sending a child's or model's text to Grafana."""
    attrs = {
        "tutor.candidate.error_type": error_type,
        "tutor.candidate.field": field,
        "tutor.candidate.retrying": retrying,
    }
    _span_event("tutor.candidate.rejected", attrs)
    _audit_logger.warning("tutor.candidate.rejected", extra={"telemetry": attrs})


def record_vlm_frames(*, count: int, mode: str) -> None:
    _vlm_frames.add(count, attributes={"vlm.mode": mode})


def record_batch(*, submitted: bool = False, fallback: bool = False) -> None:
    if submitted:
        _batch_total.add(1)
    if fallback:
        _batch_fallbacks.add(1)


def record_frame(*, result: str) -> None:
    _frames.add(1, attributes={"capture.result": result})


def record_celery_task(*, task: str, result: str, duration_ms: int) -> None:
    attrs = {"celery.task": task, "celery.result": result}
    _celery_tasks.add(1, attributes=attrs)
    _celery_duration.record(duration_ms, attributes=attrs)


def record_asr_session(*, result: str, stage: str, role: str | None = None) -> None:
    """Record only low-cardinality ASR lifecycle data, never audio or tokens."""
    attrs = _attrs(**{"asr.result": result, "asr.stage": stage, "principal.role": role})
    _asr_sessions.add(1, attributes=attrs)
    _span_event("asr.session.completed", attrs)


def _llm_original_sink() -> Path | None:
    """Return the file that keeps full model text outside Grafana.

    Non-production writes by default so a trace_id in the stdout summary can be
    joined to the original completion. Production stays off unless the explicit
    audit switch and path are both set. ``AGENT_DEBUG_AUDIT_ENABLED=false``
    disables the file in every environment.
    """
    flag = os.getenv("AGENT_DEBUG_AUDIT_ENABLED", "").strip().lower()
    if flag in {"0", "false", "no"}:
        return None
    app_env = os.getenv("APP_ENV", "development").lower()
    explicit = flag in {"1", "true", "yes"}
    if app_env == "production" and not explicit:
        return None
    configured = os.getenv("AGENT_DEBUG_AUDIT_PATH", "").strip()
    if configured:
        return Path(configured)
    if app_env == "production":
        _audit_logger.warning("agent.debug_audit.not_configured", extra={"telemetry": {"audit.kind": "output"}})
        return None
    return Path(__file__).resolve().parents[3] / "var" / "agent-llm-audit.jsonl"


def _write_debug_audit(kind: str, metadata: dict[str, Any], value: str) -> None:
    """Append the original model text to the local audit file, correlated by trace id."""
    target = _llm_original_sink()
    if target is None or kind != "output":
        return
    span_context = trace.get_current_span().get_span_context()
    record = {
        "kind": kind,
        "trace_id": format(span_context.trace_id, "032x") if span_context.is_valid else "",
        "span_id": format(span_context.span_id, "016x") if span_context.is_valid else "",
        "metadata": metadata,
        "content": _PHONE.sub("[phone]", _EMAIL.sub("[email]", value)),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        _audit_logger.exception("agent.debug_audit.write_failed", extra={"telemetry": {"audit.kind": kind}})
