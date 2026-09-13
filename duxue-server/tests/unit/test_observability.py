from __future__ import annotations

import json

from app.infrastructure.observability.telemetry import configure_observability, record_agent_input, record_model_response


def test_telemetry_is_disabled_without_an_otlp_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    assert configure_observability(component="api") is False


def test_default_agent_audit_logs_only_a_summary(caplog, monkeypatch):
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "false")
    raw = "孩子的私密提问：手机号 13800138000，邮箱 kid@example.com"
    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        record_agent_input(agent_type="tutoring", run_id="run-1", thread_id="thread-1", content=raw)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    metadata = "\n".join(str(getattr(record, "telemetry", {})) for record in caplog.records)
    assert raw not in messages
    assert raw not in metadata
    assert "input.sha256" in metadata
    assert "input.length" in metadata


def test_explicit_debug_audit_redacts_common_identifiers_and_truncates(tmp_path, monkeypatch):
    path = tmp_path / "encrypted-mount" / "audit.jsonl"
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(path))
    raw = "联系电话 13800138000，邮箱 kid@example.com，" + "x" * 200

    record_model_response(agent_type="tutoring", model="test-model", content=raw)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["metadata"]["output"]["length"] == len(raw)
    assert row["metadata"]["output"]["sha256"]
    assert "13800138000" not in row["redacted_excerpt"]
    assert "kid@example.com" not in row["redacted_excerpt"]
    assert len(row["redacted_excerpt"]) <= 160
