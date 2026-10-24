from __future__ import annotations

import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.application.workflows.planning_workflow import build_planning_graph
from app.application.workflows.tutor_loop import (
    _ensure_widget_guidelines,
    run_tutor_turn,
)
from app.application.workflows.tutor_tools import TutorToolbox
from app.contexts.tutoring.domain.tutor_permit import AttemptSummary, TutorPermit
from app.infrastructure.observability import telemetry
from tests.support.factories import create_ward
from tests.support.fakes import (
    FakeWorkflowDispatcher,
    StaticIntentClassifier,
    StaticTutorModel,
    StaticVisualLeakJudge,
    tutor_raw,
)


def _capture(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    return exporter


def test_thread_session_contains_two_tutoring_turns_then_planning_handoff(db, monkeypatch):
    exporter = _capture(monkeypatch)
    ward = create_ward(db)
    db.commit()
    classifier = StaticIntentClassifier("tutoring")
    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=classifier)

    first = coordinator.handle(
        ward_id=ward.id, content="这题我不会", thread_id=None, expected_thread_version=0, route_hint=None,
    )
    second = coordinator.handle(
        ward_id=ward.id, content="除数是 130 吗", thread_id=first.thread_id,
        expected_thread_version=first.thread_version, route_hint=None,
    )
    classifier.intent = "planning"
    third = coordinator.handle(
        ward_id=ward.id, content="帮我安排今晚的计划", thread_id=second.thread_id,
        expected_thread_version=second.thread_version, route_hint=None,
    )
    classifier.intent = "unclear"
    fourth = coordinator.handle(
        ward_id=ward.id, content="再说一遍", thread_id=third.thread_id,
        expected_thread_version=third.thread_version, route_hint=None,
    )

    assert first.thread_id == second.thread_id == third.thread_id == fourth.thread_id
    assert first.run_id == second.run_id != third.run_id
    assert fourth.run_id is None
    turns = [s for s in exporter.get_finished_spans() if s.name == "agent.turn"]
    assert len(turns) == 4
    assert all(s.attributes["langfuse.session.id"] == first.thread_id for s in turns)
    assert [s.attributes["langfuse.observation.input"] for s in turns] == [
        "这题我不会", "除数是 130 吗", "帮我安排今晚的计划", "再说一遍",
    ]
    assert [s.attributes["langfuse.observation.output"] for s in turns[:3]] == ["请回答"] * 3
    assert turns[3].attributes["langfuse.observation.output"] == "我还没确定你想做哪件事，请选择：**管理任务**、**总结思考**，还是**提问探讨**？"
    assert [s.attributes.get("langfuse.trace.metadata.run_id") for s in turns] == [
        first.run_id, second.run_id, third.run_id,
        None,
    ]
    routes = [s for s in exporter.get_finished_spans() if s.name == "agent.route"]
    assert len(routes) == 8
    assert all(s.attributes["langfuse.session.id"] == first.thread_id for s in routes)


def test_planning_graph_nodes_keep_session_context(db, monkeypatch):
    from types import SimpleNamespace

    exporter = _capture(monkeypatch)

    class FakeService:
        def save_draft(self, _ward_id, _day, _items, _pending_fields):
            return SimpleNamespace(id="draft-1", pending_fields=["tasks"])

    graph = build_planning_graph(FakeService()).compile()
    with telemetry.agent_turn_span():
        telemetry.set_agent_context(thread_id="thread-1", run_id="run-1")
        graph.invoke({"ward_id": "ward-1", "plan_date": "2026-10-22", "items": [], "pending_fields": ["tasks"]})

    nodes = [s for s in exporter.get_finished_spans() if s.name == "agent.node"]
    assert {s.attributes["agent.step"] for s in nodes} >= {
        "planning.prepare_review", "planning.route_after_prepare",
    }
    assert all(s.attributes["langfuse.session.id"] == "thread-1" for s in nodes)
    assert all(s.attributes["agent.run_id"] == "run-1" for s in nodes)


def test_tutoring_tools_and_parallel_judges_are_children_of_one_trace(monkeypatch):
    exporter = _capture(monkeypatch)
    visual = {
        "kind": "segment", "alt": "小明 3 份，小红 5 份，合计未知",
        "bars": [
            {"label": "小明", "segments": [{"value": 3}]},
            {"label": "小红", "segments": [{"value": 5}]},
        ],
        "brackets": [{"bar": 1, "label": "合计", "unknown": True}],
    }
    model = StaticTutorModel(
        {"tool": "get_task_context", "args": {}},
        tutor_raw("guide", "先看看谁多谁少？", relation="same", visual=visual),
    )
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    with telemetry.agent_turn_span():
        telemetry.set_agent_context(thread_id="thread-1", run_id="run-1")
        result = run_tutor_turn(
            model, {}, "{}", [], [], tools, permit=TutorPermit(True, AttemptSummary()),
            leak_judge=StaticVisualLeakJudge(), task_title="应用题", problem_summary="小明和小红各有几份",
        )
        _ensure_widget_guidelines([])
        tools.run("private-child-tool-name", {"query": "private-child-query"})

    assert result.vetting is not None and result.vetting.failure is None
    spans = exporter.get_finished_spans()
    steps = {(s.name, s.attributes.get("agent.step")): s for s in spans}
    tool = steps[("agent.tool", "get_task_context")]
    preloaded = steps[("agent.tool", "widget_guidelines")]
    unknown = steps[("agent.tool", "unknown_tool")]
    assert tool.attributes["agent.tool.source"] == "model_request"
    assert tool.attributes["agent.tool.status"] == "no_match"
    assert preloaded.attributes["agent.tool.source"] == "preloaded"
    assert unknown.attributes["agent.tool.status"] == "tool_error"
    assert json.loads(unknown.attributes["langfuse.observation.input"]) == {"query": "private-child-query"}
    assert json.loads(unknown.attributes["langfuse.observation.output"])["tool"] == "private-child-tool-name"
    for name in ("tutoring.candidate_schema", "tutoring.visual_schema", "tutoring.exit_gate",
                 "tutoring.text_leak", "tutoring.visual_leak"):
        assert ("agent.check", name) in steps
        assert steps[("agent.check", name)].context.trace_id == tool.context.trace_id
        assert steps[("agent.check", name)].attributes["langfuse.session.id"] == "thread-1"
