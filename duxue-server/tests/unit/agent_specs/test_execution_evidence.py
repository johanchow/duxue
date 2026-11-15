from contextlib import contextmanager
from types import SimpleNamespace as Obj

import pytest

from app.agent_specs.execution_trace import Recorder, observe_model, recorder
from app.infrastructure.observability.telemetry import (
    model_call_span,
    record_model_response,
)


def test_model_evidence_keeps_inputs_raw_output_errors_and_repeated_attempts():
    trace = Recorder()
    with trace.capture():
        for _ in range(2):
            with model_call_span(operation="test", model="fake", component_id="tutoring.turn",
                                 input_payload=[{"role": "user", "content": "test input"}]) as usage:
                record_model_response(agent_type="tutoring", model="fake", content='{"act":"guide"}')
                usage.update(tokens_in=3, tokens_out=5)
        with pytest.raises(ValueError):
            with model_call_span(operation="test", model="fake", component_id="tutoring.turn"):
                raise ValueError("provider failure")
    assert recorder() is None
    assert len(trace.events) == 3
    assert [e["status"] for e in trace.events] == ["succeeded", "succeeded", "failed"]
    assert trace.events[0]["output"] == '{"act":"guide"}'
    assert trace.events[0]["input"][0]["content"] == "test input"
    assert trace.events[0]["tokens_out"] == 5
    assert trace.events[2]["error"] == "ValueError"
    doc = trace.document()
    assert doc["schema_version"] == "duxue-execution.v1"
    assert doc["catalog"]["workflows"]
    assert all("prompt" not in d for d in doc["catalog"]["definitions"].values())


def test_recorder_preserves_parallel_branch_results_and_never_invents_unvisited_nodes():
    from app.agent_specs.runtime import execute_workflow
    from tests.unit.agent_specs.test_runtime_contracts import _conditional_spec

    trace = Recorder()
    with trace.capture():
        execute_workflow(_conditional_spec(), handlers={"demo.propose": lambda state: {"ok": True},
                                                      "demo.check": lambda state: pytest.fail("unselected gate ran")},
                         conditions={"needs_check": lambda state: False, "skip_check": lambda state: True})
    assert not any(e.get("node_id") == "demo.check" for e in trace.events)
    edges = [e for e in trace.events if e["kind"] == "edge"]
    assert next(e for e in edges if e["condition_id"] == "needs_check")["selected"] is False
    assert next(e for e in edges if e["condition_id"] == "skip_check")["selected"] is True


def test_native_execution_uploads_frozen_graph_without_evaluator_or_model_calls():
    from evals.platform.native import NativeScorer
    outputs = []

    @contextmanager
    def start(**kwargs):
        assert kwargs["name"] == "eval.execution"
        yield Obj(update=lambda **kw: outputs.append(kw))

    scorer = NativeScorer(Obj(start_as_current_observation=start), {})
    with scorer.capture_execution(case_id="synthetic", check_id="one") as recording:
        with recording.step(kind="agent", node_id="tutoring.generate", workflow_id="tutoring", input={"token": "secret", "question": "hello"}) as e:
            e["output"] = {"message": "hello"}
    output = outputs[0]["output"]
    assert "tutoring" in output["catalog"]["workflows"]
    assert output["events"][0]["input"] == {"question": "hello"}
    assert output["events"][0]["status"] == "succeeded"


def test_unsampled_runtime_executes_without_capturing_payload(monkeypatch):
    from app.agent_specs.execution_trace import record_workflow_execution
    from app.infrastructure.observability import telemetry

    @contextmanager
    def start(*args, **kwargs):
        yield Obj(is_recording=lambda: False)

    monkeypatch.setattr(telemetry, "_langfuse_enabled", lambda: True)
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda *a: Obj(start_as_current_span=start))

    @record_workflow_execution
    def business():
        assert recorder() is None
        return "unchanged"

    assert business() == "unchanged"
