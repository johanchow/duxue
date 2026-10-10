from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.infrastructure.observability.telemetry import (
    configure_observability,
    record_agent_input,
    record_companion_rejection,
    record_model_response,
    record_planning_input_rejected,
    record_tutor_candidate_rejection,
)


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


def test_tutor_candidate_rejection_records_only_low_cardinality_diagnostics(caplog):
    with caplog.at_level("WARNING", logger="duxue.agent.audit"):
        record_tutor_candidate_rejection(error_type="missing", field="same_problem", retrying=True)

    telemetry = next(getattr(record, "telemetry", {}) for record in caplog.records)
    assert telemetry == {
        "tutor.candidate.error_type": "missing",
        "tutor.candidate.field": "same_problem",
        "tutor.candidate.retrying": True,
    }


def test_model_original_is_stored_beside_the_content_free_summary(tmp_path, monkeypatch, caplog):
    path = tmp_path / "encrypted-mount" / "audit.jsonl"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "true")
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(path))
    raw = "联系电话 13800138000，邮箱 kid@example.com，" + "已从图片整理出数学口算" + "x" * 200

    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        record_model_response(agent_type="planning", model="qwen3-vl-flash", content=raw, operation="plan_intake")

    stdout = "\n".join(str(getattr(record, "telemetry", {})) for record in caplog.records)
    assert raw not in stdout
    assert "已从图片整理出数学口算" not in stdout
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["metadata"]["output"]["length"] == len(raw)
    assert row["metadata"]["output"]["sha256"]
    assert row["metadata"]["llm.operation"] == "plan_intake"
    assert row["trace_id"] == ""
    assert "13800138000" not in row["content"]
    assert "kid@example.com" not in row["content"]
    assert "已从图片整理出数学口算" in row["content"]
    assert len(row["content"]) > 160


def test_production_does_not_store_model_original_unless_audit_is_enabled(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AGENT_DEBUG_AUDIT_ENABLED", raising=False)
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(path))

    record_model_response(agent_type="planning", model="qwen3-vl-flash", content="图片里的任务", operation="plan_intake")

    assert not path.exists()


def test_non_production_stores_model_original_without_an_explicit_switch(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("AGENT_DEBUG_AUDIT_ENABLED", raising=False)
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(path))

    record_model_response(agent_type="intent", model="qwen3-vl-flash", content='{"intent":"planning"}', operation="intent_proposal")

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["content"] == '{"intent":"planning"}'
    assert row["metadata"]["llm.operation"] == "intent_proposal"


def test_plan_intake_structure_log_counts_results_without_model_text(caplog, monkeypatch):
    from app.infrastructure.observability.telemetry import record_plan_intake_structure, record_planning_loop_outcome

    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "false")
    raw = '{"assistant_text":"孩子的作业：数学口算","operations":[]}'
    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        record_model_response(agent_type="planning", model="qwen3-vl-flash", content=raw, operation="plan_intake")
        record_plan_intake_structure(
            has_image=True, operation_count=0, slot_update_count=0, clarification_required=True,
        )
        record_planning_loop_outcome(status="no_op", has_image=True)

    metadata = "\n".join(str(getattr(record, "telemetry", {})) for record in caplog.records)
    assert raw not in metadata
    assert "数学口算" not in metadata
    assert "output.sha256" in metadata
    assert "'plan_intake.has_image': True" in metadata
    assert "'plan_intake.operation_count': 0" in metadata
    assert "'plan_intake.clarification_required': True" in metadata
    assert "'plan_intake.recent_utterance_count': 0" in metadata
    assert "plan_intake.item_count" not in metadata
    assert "'planning.loop_status': 'no_op'" in metadata


def test_planning_stage_span_emits_duration_breadcrumb(caplog):
    from app.infrastructure.observability.telemetry import planning_stage_span

    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        with planning_stage_span("graph_invoke", run_id="run-1"):
            pass

    assert any(record.getMessage() == "planning.stage" for record in caplog.records)
    telemetry = next(getattr(record, "telemetry", {}) for record in caplog.records if record.getMessage() == "planning.stage")
    assert telemetry["planning.stage"] == "graph_invoke"
    assert telemetry["planning.duration_ms"] is not None
    assert telemetry["run_id"] == "run-1"


def test_companion_rejection_is_structured_and_does_not_contain_request_content(caplog):
    with caplog.at_level("WARNING", logger="duxue.agent.audit"):
        record_companion_rejection(
            code="interaction_expired",
            status_code=409,
            has_thread=True,
            has_structured_command=True,
        )

    record = next(item for item in caplog.records if item.getMessage() == "companion.turn.rejected")
    telemetry = getattr(record, "telemetry", {})
    assert telemetry == {
        "companion.rejection_code": "interaction_expired",
        "http.status_code": 409,
        "companion.has_thread": True,
        "companion.has_structured_command": True,
    }


def test_planning_input_rejection_reports_shape_without_the_raw_value(caplog):
    raw = "07:41"
    with caplog.at_level("WARNING", logger="duxue.agent.audit"):
        record_planning_input_rejected(field="start_at", code="invalid_start_at", value=raw)

    record = next(item for item in caplog.records if item.getMessage() == "planning.input.rejected")
    telemetry = getattr(record, "telemetry", {})
    assert telemetry == {
        "planning.field": "start_at",
        "planning.rejection_code": "invalid_start_at",
        "planning.value_shape": "clock",
        "http.status_code": 400,
    }
    assert raw not in record.getMessage()
    assert raw not in str(telemetry)


def test_companion_turn_audits_validation_failure_without_ward_text(caplog, monkeypatch):
    from app.api.deps import Principal
    from app.api.schemas import CompanionTurnRequest
    from app.api.v1.companion import companion_turn

    class Boom:
        def __init__(self, db):
            pass

        def handle(self, **kwargs):
            raise HTTPException(400, "开始时间格式无效")

    monkeypatch.setattr("app.api.v1.companion.CompanionCoordinator", Boom)
    db = MagicMock()
    uttered = "七点四十一分出发"
    with caplog.at_level("WARNING", logger="duxue.agent.audit"), pytest.raises(HTTPException):
        companion_turn(
            CompanionTurnRequest(content=uttered, thread_id="thread-1", expected_thread_version=3),
            Principal("ward-1", "ward"),
            db,
        )

    record = next(item for item in caplog.records if item.getMessage() == "companion.turn.rejected")
    telemetry = getattr(record, "telemetry", {})
    assert telemetry["companion.rejection_code"] == "invalid_start_at"
    assert telemetry["http.status_code"] == 400
    assert telemetry["companion.has_thread"] is True
    assert uttered not in str(telemetry)
    db.rollback.assert_called_once()
