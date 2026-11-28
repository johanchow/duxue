"""Unit and contract tests for Slice 1: Unified Skill/Tool Registry, RolePolicy,
EduAgentOrchestrator, adult read-only context_ward_id, and CreationFootprintRecorded.v1.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.application.agent.orchestrator import (
    AgentRunStore,
    EduAgentOrchestrator,
    OrchestratorStep,
)
from app.application.agent.registry import ToolContext
from app.application.agent.role_policy import evaluate_role_policy
from app.application.commands import creative_works
from app.application.commands.creation_footprints import (
    consume_pending_creation_footprints,
    list_evening_creation_footprints,
)
from app.application.tools.core_tools import build_default_registries
from app.infrastructure.persistence.models import (
    ConversationThread,
    DerivedSignal,
    GuardianWard,
    LearningEvent,
    OutboxEvent,
)
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian, create_ward


def test_default_registries_validate_5_skills_and_11_tools():
    tool_reg, skill_reg = build_default_registries()
    assert len(tool_reg.list_specs()) == 11
    adult_policy = evaluate_role_policy(role="teacher", context_ward_bound=True)
    ward_policy = evaluate_role_policy(role="ward", context_ward_bound=False)
    assert len(skill_reg.visible_catalog(adult_policy)) == 5
    ward_skill_ids = {item["id"] for item in skill_reg.visible_catalog(ward_policy)}
    assert ward_skill_ids == {
        "edu.homework_tutoring",
        "edu.interactive_courseware",
        "edu.creative_studio",
    }
    assert "edu.worksheet_grading" not in ward_skill_ids
    assert "edu.lesson_pack" not in ward_skill_ids


def test_role_ceiling_rejects_widening_ward_access():
    tool_reg, skill_reg = build_default_registries()
    with pytest.raises(ValueError, match="exceed code ceiling"):
        skill_reg.register_skill(
            {
                "id": "edu.worksheet_grading",
                "kind": "skill",
                "display_name": "批改",
                "description": "批改",
                "allowed_roles": ["guardian", "ward"],
                "tools": ["problem_solving.solve_and_verify"],
                "required_gates": ["artifact.verification_honesty"],
                "instructions": "test",
            }
        )
    with pytest.raises(ValueError, match="exceed code ceiling"):
        tool_reg.register_spec(
            {
                "id": "problem_solving.solve_and_verify",
                "kind": "tool",
                "owner_domain": "problem_solving",
                "description": "solve",
                "access": "read",
                "allowed_roles": ["guardian", "ward"],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "timeout_ms": 5000,
                "handler_id": "problem_solving.solve_and_verify",
            }
        )


def test_default_general_mode_blocks_write_tool_until_skill_loaded():
    tool_reg, skill_reg = build_default_registries()
    orch = EduAgentOrchestrator(
        tool_registry=tool_reg, skill_registry=skill_reg, run_store=AgentRunStore()
    )
    ctx = ToolContext(actor_id="teacher-1", actor_role="teacher")

    def planner(state):
        if state["step_index"] == 0:
            # Attempt write tool without loading a Skill -> must be denied
            return OrchestratorStep(
                action="call_tool",
                tool_id="artifact.create_or_revise",
                tool_args={"artifact_type": "lesson_pack"},
            )
        if state["step_index"] == 1:
            return OrchestratorStep(action="load_skill", skill_id="edu.lesson_pack")
        if state["step_index"] == 2:
            return OrchestratorStep(
                action="call_tool",
                tool_id="artifact.create_or_revise",
                tool_args={"artifact_type": "lesson_pack"},
            )
        return OrchestratorStep(action="respond", content="教案与变式题已生成")

    outcome = orch.run(ctx=ctx, message="帮我备一节分数除法课", planner=planner)
    assert outcome.status == "completed"
    assert outcome.active_skill_id == "edu.lesson_pack"
    assert "artifact.verification_honesty" in outcome.registered_gates
    assert outcome.tool_results[0].status == "denied"
    assert outcome.tool_results[1].status == "ok"
    assert outcome.tool_results[2].status == "ok"


def test_adult_context_ward_id_authorization_and_readonly_summary(client, db):
    guardian = create_guardian(db)
    bound_ward = create_ward(db)
    unbound_ward = create_ward(db)
    db.add(GuardianWard(guardian_id=guardian.id, ward_id=bound_ward.id))
    db.commit()

    g_headers = {
        "Authorization": "Bearer " + create_access_token(user_id=guardian.id, role="guardian")
    }
    w_headers = {
        "Authorization": "Bearer "
        + create_access_token(user_id=bound_ward.id, role="ward", ward_session_version=1)
    }

    # Unbound ward rejected with 403
    r_unbound = client.post(
        "/v1/conversations",
        headers=g_headers,
        json={"title": "备课", "context_ward_id": unbound_ward.id},
    )
    assert r_unbound.status_code == 403

    # Ward cannot bind context_ward_id
    r_ward = client.post(
        "/v1/conversations",
        headers=w_headers,
        json={"title": "自习", "context_ward_id": bound_ward.id},
    )
    assert r_ward.status_code == 403

    # Bound ward succeeds and persists on thread
    r_ok = client.post(
        "/v1/conversations",
        headers=g_headers,
        json={"title": "针对性复习", "context_ward_id": bound_ward.id},
    )
    assert r_ok.status_code == 201
    assert r_ok.json()["context_ward_id"] == bound_ward.id

    # Read-only tool reads summary without writing any Memory records
    tool_reg, skill_reg = build_default_registries()
    orch = EduAgentOrchestrator(tool_registry=tool_reg, skill_registry=skill_reg)
    before_events = db.query(LearningEvent).count()
    ctx = ToolContext(
        actor_id=guardian.id,
        actor_role="guardian",
        context_ward_id=bound_ward.id,
        db=db,
    )

    def planner(state):
        if state["step_index"] == 0:
            return OrchestratorStep(action="call_tool", tool_id="ward_context.read_summary", tool_args={})
        return OrchestratorStep(action="respond", content="已读取学情")

    out = orch.run(ctx=ctx, message="看看孩子最近卡点", planner=planner)
    assert out.tool_results[0].status == "ok"
    assert out.tool_results[0].data["read_only"] is True
    assert db.query(LearningEvent).count() == before_events


def test_agent_api_catalog_turns_sse_and_cancel(client, db):
    guardian = create_guardian(db)
    db.commit()
    headers = {
        "Authorization": "Bearer " + create_access_token(user_id=guardian.id, role="guardian")
    }
    cat = client.get("/v1/agent/catalog", headers=headers)
    assert cat.status_code == 200
    assert len(cat.json()["skills"]) == 5

    turn = client.post(
        "/v1/agent/turns",
        headers=headers,
        json={"message": "帮我备课", "skill_hint": "edu.lesson_pack"},
    )
    assert turn.status_code == 200
    payload = turn.json()
    assert payload["active_skill_id"] == "edu.lesson_pack"
    assert "artifact.verification_honesty" in payload["registered_gates"]

    sse = client.get(f"/v1/agent/runs/{payload['run_id']}/events", headers=headers)
    assert sse.status_code == 200
    assert "event: skill_loaded" in sse.text
    assert "event: completed" in sse.text

    cancel = client.post(f"/v1/agent/runs/{payload['run_id']}/cancel", headers=headers)
    assert cancel.status_code == 200


def test_creation_footprint_consumer_idempotent_and_isolated(db):
    from app.agent_specs.creative_work import Story

    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360"><circle cx="170" cy="100" r="60" fill="gold"/></svg>'
    story = Story.model_validate(
        {
            "title": "火星小狗",
            "pages": [{"text": "出发去火星。", "illustration": {"kind": "svg", "alt": "火星", "svg": svg}}],
        }
    )
    interaction = {"candidate": story.model_dump()}
    creative_works.persist_candidate(db, thread, interaction)
    work = db.query(creative_works.CreativeWork).filter_by(id=interaction["artifact_id"]).one()
    creative_works.apply(db, work, "save")
    db.commit()

    assert db.query(OutboxEvent).filter_by(event_type="CreationFootprintRecorded.v1", status="pending").count() == 1
    assert consume_pending_creation_footprints(db) == 1
    assert consume_pending_creation_footprints(db) == 0

    signals = db.query(DerivedSignal).filter_by(ward_id=ward.id).all()
    assert len(signals) == 1
    assert signals[0].signal_type == "interest_signal"
    assert "火星小狗" in signals[0].statement

    today = datetime.now(timezone.utc).astimezone().date()
    footprints = list_evening_creation_footprints(db, ward_id=ward.id, local_date=today)
    assert len(footprints) == 1
    assert footprints[0]["title"] == "火星小狗"
