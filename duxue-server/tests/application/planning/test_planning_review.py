"""Plan review renders the validated draft without another model request."""

from datetime import date

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from app.application.commands.plan_intake import PlanIntakeResult, PlanIntakeService
from app.application.ports.companion import RunInvocation
from app.application.workflows.planning_adapter import PlanningWorkflowAdapter
from app.infrastructure.ai import components
from app.infrastructure.persistence.models import (
    AgentRun,
    ConversationThread,
    PlanDraft,
    Task,
)
from tests.support.factories import create_ward

DAY = date(2026, 11, 8)


@pytest.fixture(autouse=True)
def guard_external_ai_gateway(monkeypatch):
    # Replace the global guard so the former reply adapter cannot silently fall
    # back after attempting a forbidden extra model request.
    def unexpected_model_call(**kwargs):
        pytest.fail("plan review must not request a model")

    monkeypatch.setattr(components, "invoke_json_component", unexpected_model_call)


@pytest.mark.parametrize("natural_language", [False, True])
@pytest.mark.parametrize("stale_version", [False, True])
def test_review_and_confirmation_use_draft_without_extra_model(db, monkeypatch, natural_language, stale_version):
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    run = AgentRun(thread_id=thread.id, ward_id=ward.id, agent_type="planning", run_ref="review")
    db.add(run)
    db.flush()
    monkeypatch.setattr("app.application.workflows.planning_adapter.planning_today", lambda: DAY)
    intake_calls = []

    def respond(self, **kwargs):
        intake_calls.append(kwargs)
        return PlanIntakeResult(
            assistant_text="模型候选话术不能替代最终草稿确认。",
            operations=[{"kind": "create", "title": "数学"}],
        )

    monkeypatch.setattr(PlanIntakeService, "respond", respond)
    adapter = PlanningWorkflowAdapter(db, checkpointer=InMemorySaver())
    invocation = RunInvocation(
        run_id=run.id, thread_id=thread.id, ward_id=ward.id, agent_type="planning",
        command_id="review", turn={"content": "先写数学"} if natural_language else {
            "planning_items": [{"new_task": True, "title": "数学"}],
        },
    )
    review = adapter.invoke(invocation=invocation).next_interaction
    assert len(intake_calls) == int(natural_language)
    assert review["kind"] == "plan_confirm_list"
    assert "请确认这些事项和顺序。" in review["content"]
    assert "模型候选话术" not in review["content"]
    assert review["card_snapshot"]["items"][0]["title"] == "数学"
    assert review["actions"][0]["command"] == "confirm_plan"
    assert review["actions"][0]["enabled"]
    assert not {"model", "model_guidance", "model_fallback"}.intersection(review)
    assert all(task.schedule_id is None for task in db.query(Task))
    draft = db.get(PlanDraft, review["object_ref"]["object_id"])

    def confirm(version):
        return adapter.invoke(invocation=invocation.model_copy(update={
            "command_id": "confirm", "turn": {"structured_command": {
                "command": "confirm_plan", "payload": {
                    "draft_id": draft.id, "expected_draft_version": version,
                },
            }},
        }))

    if stale_version:
        with pytest.raises(HTTPException) as stale:
            confirm(draft.version - 1)
        assert stale.value.status_code == 409
        assert all(task.schedule_id is None for task in db.query(Task))
    else:
        outcome = confirm(draft.version)
        assert outcome.run_status == "closed"
        assert outcome.next_interaction["status"] == "confirmed"
        assert db.query(Task).one().schedule_id is not None
        assert not {"model", "model_guidance", "model_fallback"}.intersection(outcome.next_interaction)
    assert len(intake_calls) == int(natural_language)
