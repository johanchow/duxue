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


def test_telemetry_is_disabled_without_an_otlp_endpoint_or_langfuse(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    assert configure_observability(component="api") is False


def test_model_span_includes_langfuse_generation_input_and_output(monkeypatch):
    from contextlib import contextmanager

    from app.infrastructure.observability import telemetry

    class Span:
        def __init__(self):
            self.attributes = {}
            self.name = "llm.request"

        def is_recording(self):
            return True

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def add_event(self, _name, attributes):
            pass

        def record_exception(self, _error):
            raise AssertionError("unexpected model error")

        def set_status(self, _status):
            raise AssertionError("unexpected model error")

    captured = Span()

    class Tracer:
        @contextmanager
        def start_as_current_span(self, _name, attributes, **_kwargs):
            captured.attributes.update(attributes)
            yield captured

    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda _name: Tracer())
    monkeypatch.setattr(telemetry.trace, "get_current_span", lambda: captured)
    monkeypatch.setattr(telemetry, "_write_debug_audit", lambda *_args: None)
    with telemetry.model_call_span(
        operation="tutor_turn", model="qwen-test", agent_type="tutoring",
        component_id="tutoring.turn", component_version="v1",
        input_payload=[{"role": "user", "content": "孩子的题目"}],
    ) as result:
        result["tokens_in"] = 12
        result["tokens_out"] = 34
        telemetry.record_model_response(agent_type="tutoring", model="qwen-test", content='{"reply":"模型原文"}')

    assert captured.attributes["langfuse.observation.type"] == "generation"
    assert captured.attributes["langfuse.observation.metadata.kind"] == "agent"
    assert captured.attributes["langfuse.observation.metadata.kind_id"] == "tutoring.turn"
    assert captured.attributes["agent.unit.id"] == "tutoring.turn"
    assert captured.attributes["langfuse.observation.metadata.component_id"] == "tutoring.turn"
    assert captured.attributes["langfuse.observation.model.name"] == "qwen-test"
    assert json.loads(captured.attributes["langfuse.observation.usage_details"]) == {"input": 12, "output": 34}
    assert json.loads(captured.attributes["langfuse.observation.input"]) == [
        {"role": "user", "content": "孩子的题目"},
    ]
    assert captured.attributes["langfuse.observation.output"] == '{"reply":"模型原文"}'


def test_leak_judge_generation_is_labeled_as_its_gate(monkeypatch):
    from contextlib import contextmanager

    from app.infrastructure.observability import telemetry

    class Span:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def set_status(self, _status):
            raise AssertionError("unexpected model error")

    captured = Span()

    class Tracer:
        @contextmanager
        def start_as_current_span(self, _name, attributes, **_kwargs):
            captured.attributes.update(attributes)
            yield captured

    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda _name: Tracer())
    with telemetry.model_call_span(
        operation="tutor_leak_check", model="qwen-judge", component_id="tutoring.leak-judge",
    ):
        pass
    assert captured.attributes["langfuse.observation.metadata.kind"] == "gate"
    assert captured.attributes["langfuse.observation.metadata.kind_id"] == "tutoring.leak-judge"
    assert captured.attributes["langfuse.observation.metadata.node_id"] == "tutoring-vet.text_leak"
    assert captured.attributes["langfuse.observation.metadata.workflow_id"] == "tutoring-vet"
    assert captured.attributes["agent.unit.kind"] == "gate"


def test_langfuse_model_payload_keeps_image_for_media_upload_and_grafana_omits_bytes():
    from app.infrastructure.observability.telemetry import (
        _grafana_span_attributes,
        _langfuse_payload,
    )

    payload = [{"role": "user", "content": [
        {"type": "text", "text": "这道题怎么做？"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,secret"}},
    ]}]
    encoded = _langfuse_payload(payload)
    assert json.loads(encoded)[0]["content"][0]["text"] == "这道题怎么做？"
    assert json.loads(encoded)[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,secret"
    grafana = _grafana_span_attributes({"langfuse.observation.input": encoded})
    assert json.loads(grafana["langfuse.observation.input"])[0]["content"][1]["image_url"] == "[image omitted]"
    assert "base64" not in grafana["langfuse.observation.input"]


def test_grafana_exporter_scrubs_image_without_changing_langfuse_span(monkeypatch):
    from langfuse._client.span_exporter import LangfuseTransformingSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    captured = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(captured))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with telemetry.agent_turn_span():
        telemetry.record_agent_input(
            agent_type="tutoring", run_id=None, thread_id="thread-1",
            content="看这张图", images=["data:image/png;base64,secret"],
        )
    original = captured.get_finished_spans()[0]

    class Sink:
        def export(self, spans):
            self.spans = spans
            return True

    sink = Sink()
    telemetry._GrafanaSpanExporter(sink).export([original])
    assert "data:image/png;base64,secret" in original.attributes["langfuse.observation.input"]
    assert "base64" not in sink.spans[0].attributes["langfuse.observation.input"]
    assert sink.spans[0].context == original.context

    media_seen = []

    class MediaManagerSpy:
        def _find_and_process_media(self, **kwargs):
            media_seen.append(kwargs["data"])
            return kwargs["data"]

    LangfuseTransformingSpanExporter(
        exporter=InMemorySpanExporter(), media_manager=MediaManagerSpy(), mask_otel_spans=None,
    ).export([original])
    assert media_seen[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,secret"


def test_agent_session_includes_route_and_model_before_run_and_root_text(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with telemetry.agent_turn_span():
        telemetry.set_agent_context(thread_id="thread-1")
        with telemetry.agent_step_span("route", "intent_route"), telemetry.model_call_span(
            operation="intent", model="qwen-test",
        ):
            pass
        telemetry.set_agent_context(run_id="run-1")
        telemetry.record_agent_input(
            agent_type="tutoring", run_id="run-1", thread_id="thread-1", content="孩子的原话",
        )
        telemetry.record_agent_output("展示给孩子的回复")
        with telemetry.agent_workflow_span(agent_type="tutoring", run_id="run-1", thread_id="thread-1"):
            telemetry.record_llm_fallback(operation="tutor_turn", reason="child-secret-in-error")
            with telemetry.agent_step_span("tool", "get_task_context") as tool:
                tool.set_attribute("agent.tool.status", "unique")

    spans = exporter.get_finished_spans()
    assert all(telemetry._should_export_to_langfuse(span) for span in spans)
    by_name = {span.name: span for span in spans}
    assert {"agent.turn", "agent.route", "agent.workflow", "agent.tool", "llm.request"} <= by_name.keys()
    assert all(span.attributes["langfuse.session.id"] == "thread-1" for span in spans)
    assert by_name["agent.turn"].attributes["langfuse.trace.metadata.run_id"] == "run-1"
    assert "agent.run_id" not in by_name["agent.route"].attributes
    assert "agent.run_id" not in by_name["llm.request"].attributes
    assert by_name["agent.tool"].attributes["agent.run_id"] == "run-1"
    assert by_name["llm.request"].parent.span_id == by_name["agent.route"].context.span_id
    assert by_name["agent.tool"].parent.span_id == by_name["agent.workflow"].context.span_id
    exported = str([(s.attributes, [(e.name, e.attributes) for e in s.events]) for s in spans])
    assert by_name["agent.turn"].attributes["langfuse.observation.metadata.kind"] == "workflow"
    assert by_name["agent.turn"].attributes["langfuse.observation.metadata.kind_id"] == "companion"
    assert by_name["agent.route"].attributes["langfuse.observation.metadata.kind_id"] == "companion.intent"
    assert by_name["agent.workflow"].attributes["langfuse.observation.metadata.kind_id"] == "tutoring"
    assert by_name["agent.tool"].attributes["langfuse.observation.metadata.kind"] == "tool"
    assert by_name["agent.tool"].attributes["langfuse.observation.metadata.kind_id"] == "tutoring.get_task_context"
    assert by_name["llm.request"].attributes["langfuse.observation.metadata.kind"] == "external"
    assert by_name["llm.request"].attributes["langfuse.observation.metadata.kind_id"] == "intent"
    assert by_name["agent.turn"].attributes["langfuse.observation.input"] == "孩子的原话"
    assert by_name["agent.turn"].attributes["langfuse.observation.output"] == "展示给孩子的回复"
    assert "input.text" not in str(by_name["agent.turn"].events)
    assert "child-secret-in-error" not in exported


def test_grafana_parent_keeps_input_event_and_langfuse_turn_has_input(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with provider.get_tracer("http").start_as_current_span("HTTP POST"), telemetry.agent_turn_span():
        telemetry.set_agent_context(thread_id="thread-1")
        telemetry.record_agent_input(
            agent_type="tutoring", run_id=None, thread_id="thread-1", content="孩子的原话",
        )

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["HTTP POST"].events[0].attributes["input.text"] == "孩子的原话"
    assert "input.text" not in spans["agent.turn"].events[0].attributes
    assert spans["agent.turn"].attributes["langfuse.observation.input"] == "孩子的原话"
    assert telemetry._should_export_to_langfuse(spans["HTTP POST"]) is False


def test_committed_subgoal_and_shown_reply_are_joinable_in_trace_and_logs(monkeypatch, caplog):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with caplog.at_level("INFO", logger="duxue.agent.audit"), telemetry.agent_turn_span():
        telemetry.set_agent_context(thread_id="thread-1", run_id="run-1")
        with telemetry.agent_step_span("node", "tutoring.apply_problem"):
            telemetry.stage_tutor_subgoal_transition(
                problem_id="problem-1", turn_id="turn-1", previous="先列式",
                candidate="先移项", applied="先移项",
            )
        telemetry.record_tutor_subgoal_committed()
        telemetry.record_agent_output("先看看等式两边能怎样整理？")

    node = next(s for s in exporter.get_finished_spans() if s.attributes.get("agent.step") == "tutoring.apply_problem")
    assert json.loads(node.attributes["langfuse.observation.input"])["candidate_next_subgoal"] == "先移项"
    assert json.loads(node.attributes["langfuse.observation.output"])["active_subgoal"] == "先移项"
    logged = [record.telemetry for record in caplog.records if hasattr(record, "telemetry")]
    assert any(item.get("active_subgoal") == "先移项" and item.get("agent.run_id") == "run-1" for item in logged)
    assert any(item.get("shown") == "先看看等式两边能怎样整理？" for item in logged)


def test_exported_model_error_records_class_only(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    with pytest.raises(ValueError, match="private-child-content"), telemetry.model_call_span(
        operation="intent", model="qwen-test",
    ):
        raise ValueError("private-child-content")

    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "ValueError"
    assert not span.events
    assert "private-child-content" not in str(span.attributes)
    assert "private-child-content" not in str(span.status)


def test_langfuse_requires_an_explicit_enabled_flag_and_both_keys(monkeypatch):
    from app.infrastructure.observability.telemetry import _langfuse_enabled

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert _langfuse_enabled() is False

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    assert _langfuse_enabled() is True


def test_agent_input_log_carries_the_question_with_contact_details_masked(caplog, monkeypatch):
    """孩子的问话进入 Grafana/Loki 以便审计；手机号和邮箱先遮蔽，长度与摘要仍保留。"""
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "false")
    raw = "自转和公转有什么区别？手机号 13800138000，邮箱 kid@example.com"
    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        record_agent_input(agent_type="tutoring", run_id="run-1", thread_id="thread-1", content=raw)

    metadata = "\n".join(str(getattr(record, "telemetry", {})) for record in caplog.records)
    assert "自转和公转有什么区别？" in metadata
    assert "13800138000" not in metadata and "kid@example.com" not in metadata
    assert "[phone]" in metadata and "[email]" in metadata
    assert "input.sha256" in metadata and "input.length" in metadata


def test_agent_input_text_is_capped_in_grafana(caplog, monkeypatch):
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_ENABLED", "false")
    with caplog.at_level("INFO", logger="duxue.agent.audit"):
        record_agent_input(agent_type="tutoring", run_id=None, thread_id=None, content="问" * 5000)
    telemetry = caplog.records[-1].telemetry
    assert len(telemetry["input.text"]) == 2000 and telemetry["input.length"] == 5000


def test_audit_file_joins_input_model_output_and_result_by_trace_id(tmp_path, monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    from app.infrastructure.observability.telemetry import record_tutor_turn_result

    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("AGENT_DEBUG_AUDIT_ENABLED", raising=False)
    monkeypatch.setenv("AGENT_DEBUG_AUDIT_PATH", str(path))
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("turn") as span:
        record_agent_input(agent_type="tutoring", run_id="run-1", thread_id="t-1", content="自转和公转有什么区别？")
        record_model_response(agent_type="tutoring", model="m", content='{"act":"answer"}', operation="tutor_turn")
        record_tutor_turn_result(
            act="answer", relation="new", student_move="request_answer", outcome="shown", reason=None, shown="自转管昼夜。",
            visual_dropped="visual_invalid", shape_flags=["too_long"],
        )
        trace_id = format(span.get_span_context().trace_id, "032x")

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == ["input", "output", "turn_result"]
    assert {row["trace_id"] for row in rows} == {trace_id}
    assert rows[0]["content"] == "自转和公转有什么区别？" and rows[0]["metadata"]["agent.run_id"] == "run-1"
    assert rows[2]["content"] == "自转管昼夜。"
    assert rows[2]["metadata"] == {
        "tutor.act": "answer", "tutor.relation": "new", "tutor.student_move": "request_answer", "tutor.outcome": "shown",
        "tutor.visual.dropped": "visual_invalid", "tutor.shape.flags": "too_long",
    }


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
    from app.infrastructure.observability.telemetry import (
        record_plan_intake_structure,
        record_planning_loop_outcome,
    )

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
