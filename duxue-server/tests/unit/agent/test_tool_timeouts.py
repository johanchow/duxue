from contextvars import ContextVar
from threading import BoundedSemaphore, Event, get_ident

import pytest

from app.application.agent import registry
from app.application.agent.registry import ToolContext, ToolExecutor
from app.application.agent.role_policy import evaluate_role_policy
from app.application.tools.core_tools import build_default_registries
from app.infrastructure.ai import client as model_client


def execute(handler, *, command=False, db=None):
    tools, _ = build_default_registries()
    tool = "artifact.create_or_revise" if command else "math.compute"
    spec = tools.get_spec(tool).model_copy(update={"timeout_ms": 100})
    tools.register_spec(spec)
    tools.register_handler(spec.handler_id, handler)
    return ToolExecutor(tools).execute(
        tool_id=tool,
        args={} if command else {"op": "test"},
        ctx=ToolContext(actor_id="test", actor_role="guardian", db=db),
        policy=evaluate_role_policy(role="guardian"),
        active_tools=frozenset({tool}),
    )


def test_read_timeout_returns_before_handler_finishes_and_discards_late_success():
    started, release, finished = Event(), Event(), Event()

    def handler(args, ctx):
        started.set()
        try:
            release.wait(5)
            return {"late": True}
        finally:
            finished.set()

    try:
        result = execute(handler)
        assert started.is_set()
        assert not finished.is_set()
        assert result.status == "tool_error"
        assert result.error_code == "tool_timeout"
        assert result.data == {}
    finally:
        release.set()
        assert finished.wait(2)


def test_handler_gets_remaining_budget_and_trace_context():
    trace = ContextVar("tool_test_trace", default=None)
    token = trace.set("trace-123")
    try:

        def handler(args, ctx):
            remaining = model_client.remaining_model_time()
            assert 0 < remaining <= 0.1
            assert trace.get() == "trace-123"
            return {"ok": True}

        assert execute(handler).data == {"ok": True}
        assert model_client.remaining_model_time() is None
    finally:
        trace.reset(token)


def test_nested_model_budget_cannot_extend_tool_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model_client, "monotonic", lambda: clock[0])

    def handler(args, ctx):
        clock[0] = 0.02
        with model_client.model_time_budget(120):
            assert model_client.remaining_model_time() == pytest.approx(0.08)
        return {}

    assert execute(handler, command=True).status == "ok"
    assert model_client.remaining_model_time() is None


@pytest.mark.parametrize("command,db", [(True, None), (False, object())])
def test_transaction_bound_handlers_stay_on_caller_thread_and_reject_late_result(
    monkeypatch, command, db
):
    clock = [0.0]
    monkeypatch.setattr(model_client, "monotonic", lambda: clock[0])
    caller = get_ident()
    completed = []

    def handler(args, ctx):
        assert get_ident() == caller
        assert ctx.db is db
        clock[0] = 0.2
        completed.append(True)
        return {"late": True}

    result = execute(handler, command=command, db=db)
    assert completed == [True]
    assert result.error_code == "tool_timeout"
    assert result.data == {}


def test_tool_preserves_shorter_outer_budget_and_restores_it(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model_client, "monotonic", lambda: clock[0])
    with model_client.model_time_budget(0.05):

        def handler(args, ctx):
            assert model_client.remaining_model_time() == pytest.approx(0.05)
            return {}

        assert execute(handler, command=True).status == "ok"
        assert model_client.remaining_model_time() == pytest.approx(0.05)
    assert model_client.remaining_model_time() is None


def test_read_capacity_is_bounded_without_executing_overflow(monkeypatch):
    slots = BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(registry, "_tool_slots", slots)
    called = []
    try:
        result = execute(lambda *_: called.append(True) or {})
        assert result.error_code == "tool_capacity_exhausted"
        assert called == []
    finally:
        slots.release()


def test_timed_out_read_keeps_capacity_until_worker_exits(monkeypatch):
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(registry, "_tool_slots", slots)
    release = Event()
    try:
        assert execute(lambda *_: release.wait(5) or {}).error_code == "tool_timeout"
        assert execute(lambda *_: {}).error_code == "tool_capacity_exhausted"
    finally:
        release.set()
        assert slots.acquire(timeout=2)
        slots.release()
    assert execute(lambda *_: {}).status == "ok"


def test_tool_budget_caps_model_transport_timeout_and_disables_retries(monkeypatch):
    monkeypatch.setattr(model_client.httpx, "Client", lambda **kwargs: object())
    monkeypatch.setattr(model_client, "OpenAI", lambda **kwargs: kwargs)

    def handler(args, ctx):
        transport = model_client.dashscope_client(timeout=60)
        assert 0 < transport["timeout"] <= 0.1
        assert transport["max_retries"] == 0
        return {}

    assert execute(handler, command=True).status == "ok"


def test_expired_outer_budget_never_starts_command(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model_client, "monotonic", lambda: clock[0])
    called = []
    with model_client.model_time_budget(0.05):
        clock[0] = 0.06
        result = execute(lambda *_: called.append(True) or {}, command=True)
    assert result.error_code == "tool_timeout"
    assert called == []


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError(), "tool_timeout"),
        (PermissionError(), "access_denied"),
        (NotImplementedError(), "tool_unavailable"),
        (ValueError(), "execution_failed"),
    ],
)
def test_timeout_and_existing_error_translation(error, code):
    def handler(args, ctx):
        raise error

    assert execute(handler).error_code == code


def test_orchestrator_stops_after_tool_timeout():
    from app.application.agent.orchestrator import (
        EduAgentOrchestrator,
        OrchestratorStep,
    )

    tools, skills = build_default_registries()
    tools.register_handler(
        "math.compute", lambda *_: (_ for _ in ()).throw(TimeoutError())
    )
    steps = []

    def planner(state):
        steps.append(state["step_index"])
        return OrchestratorStep(
            action="call_tool", tool_id="math.compute", tool_args={"op": "test"}
        )

    result = EduAgentOrchestrator(tool_registry=tools, skill_registry=skills).run(
        ctx=ToolContext(actor_id="test", actor_role="guardian"),
        message="test",
        planner=planner,
    )
    assert result.status == "failed"
    assert result.tool_results[-1].error_code == "tool_timeout"
    assert steps == [0]
