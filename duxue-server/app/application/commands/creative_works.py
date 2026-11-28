"""Ward story creation and versioning. Model output never owns IDs or publication."""

from uuid import uuid4
from app.contexts.artifact_workspace.domain.versions import TEMPORARY_LIFETIME

from fastapi import HTTPException
from app.application.commands.artifact_workspace import apply as apply, delete_saved as delete_saved, rename_saved as rename_saved, view as view

from app.agent_specs.catalog import load_catalog
from app.agent_specs.runtime import execute_workflow, GateDecision
from app.agent_specs.contexts import build_context
from app.agent_specs.creative_work import AUTHOR, GATE, Story
from app.agent_specs.verdicts import normalize_judge
from app.application.ports.companion import WorkflowOutcome
from app.application.queries.run_transcript import recent_thread_utterances
from app.infrastructure.ai import components
from app.infrastructure.persistence.models import (
    CreativeWork,
    CreativeWorkVersion,
    CompanionMessage,
    Sprint,
    now,
)


def generate(payload):
    def invoke(name):
        spec = components.COMPONENTS.get(name)
        user = build_context(name, payload=payload)
        return components.invoke_json_component(spec=spec, user=user)

    def check(state):
        verdict = normalize_judge(GATE, invoke(GATE))
        state["permitted"] = verdict.verdict == "allow"
        return GateDecision(verdict.verdict, verdict.reason_code)

    result = execute_workflow(
        load_catalog().spec("ward-creative"),
        handlers={
            GATE: check,
            AUTHOR: lambda state: Story.model_validate(invoke(AUTHOR)),
        },
        conditions={
            "permitted": lambda state: state["permitted"],
            "denied": lambda state: not state["permitted"],
        },
    )
    drawing = result["results"].get("ward-creative.draw")
    return Story.model_validate(drawing.unwrap()) if drawing else None


def focus_reminder(db, invocation):
    focus_id = invocation.turn.get("off_topic_sprint_id")
    if not focus_id:
        return None
    sprint = (
        db.query(Sprint.id)
        .filter_by(id=focus_id, ward_id=invocation.ward_id, status="active")
        .first()
    )
    if not sprint:
        return None
    previous = (
        db.query(CompanionMessage)
        .filter_by(thread_id=invocation.thread_id, author_type="companion")
        .order_by(CompanionMessage.thread_version.desc())
        .first()
    )
    if previous and (previous.interaction_ref or {}).get("focus_id") == focus_id:
        return None
    return {
        "kind": "creative_focus_reminder",
        "content": "你还有一个专注挑战在进行。想先画绘本也可以，告诉我你想画的故事吧。",
        "focus_id": focus_id,
    }


def create_candidate(db, invocation):
    reminder = focus_reminder(db, invocation)
    if reminder:
        return WorkflowOutcome(
            run_status="closed", outcome_type="response", response=reminder
        )
    rows, _ = recent_thread_utterances(
        db,
        ward_id=invocation.ward_id,
        thread_id=invocation.thread_id,
        exclude_turn_id=invocation.turn_id,
    )
    payload = {"instruction": invocation.turn["content"], "recent": rows}
    db.commit()
    candidate = generate(payload)
    if candidate is None:
        text = "可以从你自己的想法开始。你最想画哪一幕？"
        return WorkflowOutcome(
            run_status="closed",
            outcome_type="response",
            response={"kind": "text", "content": text},
        )
    return WorkflowOutcome(
        run_status="closed",
        outcome_type="response",
        response={
            "kind": "creative_work",
            "content": candidate.title,
            "candidate": candidate.model_dump(),
        },
    )


def persist_candidate(db, thread, interaction):
    story = Story.model_validate(interaction.pop("candidate"))
    work = CreativeWork(
        ward_id=thread.ward_id, source_thread_id=thread.id, title=story.title, expires_at=now() + TEMPORARY_LIFETIME
    )
    db.add(work)
    db.flush()
    pages = [dict(page.model_dump(), block_id=str(uuid4())) for page in story.pages]
    db.add(CreativeWorkVersion(work_id=work.id, number=1, pages=pages))
    interaction["artifact_id"] = work.id
