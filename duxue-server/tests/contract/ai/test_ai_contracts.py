from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.ports.companion import (
    ContextEnvelope,
    ContextSpec,
    CoordinatorResult,
    RouteDecision,
    RunInvocation,
    WorkflowOutcome,
)
from app.infrastructure.ai.model_gateway import AgentTextCandidate
from app.infrastructure.persistence.models import uid


def test_context_spec_contract_defaults():
    """ContextSpec 契约：指定策略版本与最大调用次数。"""
    spec = ContextSpec(policy_version="v1", max_model_calls=1)
    assert spec.policy_version == "v1"
    assert spec.max_model_calls == 1


def test_context_envelope_trace_snapshot_redacts_sensitive_payloads():
    """ContextEnvelope.trace_snapshot 仅导出用于脱敏审计的摘要元数据，不暴露大段正文。"""
    envelope = ContextEnvelope(
        run={"run_id": uid(), "attempt": 1},
        actor={"role": "ward", "ward_id": uid()},
        objective={"goal": "tutoring"},
        session={"session_id": "study_123"},
        policy_version="v1",
        context_refs=["study_session:123"],
        signals=[{"statement": "思维导图有效"}],
        memory=[{"summary": "曾几何题受阻"}],
        profile={"learning_strategy": "step_by_step"},
    )
    snapshot = envelope.trace_snapshot()
    assert snapshot["version"] == "companion-context.v1"
    assert snapshot["signal_count"] == 1
    assert snapshot["memory_count"] == 1
    assert snapshot["has_profile"] is True
    assert "statement" not in snapshot


def test_run_invocation_and_outcome_contracts():
    """RunInvocation 与 WorkflowOutcome 契约校验。"""
    invocation = RunInvocation(
        run_id=uid(),
        thread_id=uid(),
        ward_id=uid(),
        agent_type="planning",
        turn={"content": "开始排程"},
    )
    assert invocation.attempt == 1
    assert invocation.agent_type == "planning"

    outcome = WorkflowOutcome(
        run_status="waiting_for_ward",
        outcome_type="waiting",
        next_interaction={"status": "needs_input"},
    )
    assert outcome.run_status == "waiting_for_ward"
    assert outcome.next_interaction["status"] == "needs_input"


def test_agent_text_candidate_contract_limits():
    """AgentTextCandidate 契约：长度必须在 1~1200 字符内，空文本或超长文本拒绝。"""
    valid = AgentTextCandidate(content="这是一条有效的回复")
    assert valid.content == "这是一条有效的回复"

    # 空文本拒绝
    with pytest.raises(ValidationError):
        AgentTextCandidate(content="")

    # 超长文本拒绝 (> 1200 字符)
    with pytest.raises(ValidationError):
        AgentTextCandidate(content="A" * 1201)
