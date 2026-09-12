from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ai_runtime.companion_coordinator import CompanionCoordinator
from app.ai_runtime.contracts import CoordinatorResult, RouteDecision, WorkflowOutcome
from app.models import AgentCheckpoint, AgentRun, AgentStreamEvent, AgentTrace, ConversationThread, uid
from tests.support.factories import create_ward
from tests.support.fakes import FakeWorkflowDispatcher


def test_coordinator_handles_turn_and_records_trace_and_stream_event(db):
    """协调器编排用例：分配 Thread/Run，调用工作流，更新版本，写入审计 Trace 与流事件。"""
    ward = create_ward(db)
    db.commit()

    dispatcher = FakeWorkflowDispatcher(
        WorkflowOutcome(
            run_status="waiting_for_ward",
            outcome_type="waiting",
            response={"content": "这是第一步指引"},
            checkpoint_ref="chk:test:1",
        )
    )
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher)

    result = coordinator.handle(
        ward_id=ward.id,
        content="帮我安排复习计划",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
    )

    assert result.thread_id is not None
    assert result.thread_version == 2
    assert result.run_id is not None
    assert result.run_status == "waiting_for_ward"

    # 验证 AgentTrace 记录
    trace = db.query(AgentTrace).filter_by(thread_id=result.thread_id).first()
    assert trace is not None
    assert trace.route_target == "planning"
    assert trace.route_mode in {"start", "continue"}

    # 验证 AgentStreamEvent
    event = db.query(AgentStreamEvent).filter_by(run_id=result.run_id).first()
    assert event is not None
    assert event.payload == {"content": "这是第一步指引"}

    # 验证 Checkpoint
    checkpoint = db.query(AgentCheckpoint).filter_by(run_id=result.run_id).first()
    assert checkpoint is not None
    assert checkpoint.checkpoint_ref == "chk:test:1"


def test_coordinator_fences_late_outcome_and_records_discard_trace(db):
    """Fencing 防御：迟到的 Outcome（如 turn_id 已变）必须被静默丢弃，且记录审计 Trace。"""
    ward = create_ward(db)
    db.commit()

    coordinator = CompanionCoordinator(db, dispatcher=FakeWorkflowDispatcher())
    result = coordinator.handle(
        ward_id=ward.id,
        content="排个计划",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
    )

    run = db.get(AgentRun, result.run_id)
    thread = db.get(ConversationThread, result.thread_id)

    # 模拟外部一个伪造/迟到的 Outcome，使用过期的 turn_id
    stale_turn_id = uid()
    fake_outcome = WorkflowOutcome(
        run_status="closed",
        outcome_type="completed",
        response={"content": "迟到的结果"},
    )

    accepted = coordinator.record_outcome(
        run_id=run.id,
        thread_id=thread.id,
        ward_id=ward.id,
        turn_id=stale_turn_id,
        attempt=run.attempt,
        outcome=fake_outcome,
        decision=RouteDecision(target="planning", mode="continue", confidence=1.0, route_reason="test"),
        duration_ms=10,
    )
    assert accepted is False

    # 状态不能被篡改
    run_refreshed = db.get(AgentRun, run.id)
    assert run_refreshed.status != "closed"

    # 应写入一条丢弃审计 Trace
    discard_trace = (
        db.query(AgentTrace)
        .filter(AgentTrace.run_id == run.id)
        .order_by(AgentTrace.created_at.desc())
        .first()
    )
    assert discard_trace.outcome.get("late_outcome_discarded") is True


def test_coordinator_command_id_idempotency_and_digest_conflict(db):
    """Command ID 幂等与冲突检测。"""
    ward = create_ward(db)
    db.commit()

    dispatcher = FakeWorkflowDispatcher()
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher)
    command_id = uid()

    # 第一次调用
    res1 = coordinator.handle(
        ward_id=ward.id,
        content="安排数学任务",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
        command_id=command_id,
    )
    assert len(dispatcher.invocations) == 1

    # 相同 command_id + 相同参数，重放返回相同结果，不再调用 dispatcher
    res2 = coordinator.handle(
        ward_id=ward.id,
        content="安排数学任务",
        thread_id=None,
        expected_thread_version=0,
        route_hint=None,
        command_id=command_id,
    )
    assert res1.model_dump() == res2.model_dump()
    assert len(dispatcher.invocations) == 1

    # 相同 command_id 但参数不同，抛出 409
    with pytest.raises(HTTPException) as exc:
        coordinator.handle(
            ward_id=ward.id,
            content="篡改后的不同请求内容",
            thread_id=None,
            expected_thread_version=0,
            route_hint=None,
            command_id=command_id,
        )
    assert exc.value.status_code == 409
    assert "different payload" in exc.value.detail


def test_coordinator_thread_version_optimistic_locking(db):
    """乐观锁：expected_thread_version 滞后时抛出 409。"""
    ward = create_ward(db)
    db.commit()

    coordinator = CompanionCoordinator(db, dispatcher=FakeWorkflowDispatcher())
    res1 = coordinator.handle(
        ward_id=ward.id,
        content="你好",
        thread_id=None,
        expected_thread_version=0,
        route_hint="planning",
    )
    assert res1.thread_version == 2

    # 客户端依然带着旧版本号 1 重试新请求
    with pytest.raises(HTTPException) as exc:
        coordinator.handle(
            ward_id=ward.id,
            content="再帮我排一下",
            thread_id=res1.thread_id,
            expected_thread_version=1,  # 数据库当前是 2
            route_hint="planning",
        )
    assert exc.value.status_code == 409
    assert "conversation thread has changed" in exc.value.detail
