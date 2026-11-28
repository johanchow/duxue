"""Ward story creation and versioning. Model output never owns IDs or publication."""

from uuid import uuid4
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func

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
    CreativeWorkCommand,
    OutboxEvent,
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
    sprint = (
        db.query(Sprint.id)
        .filter_by(ward_id=invocation.ward_id, status="active")
        .first()
    )
    if not sprint:
        return None
    focus_id = sprint[0]
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
        ward_id=thread.ward_id, source_thread_id=thread.id, title=story.title
    )
    db.add(work)
    db.flush()
    pages = [dict(page.model_dump(), block_id=str(uuid4())) for page in story.pages]
    db.add(CreativeWorkVersion(work_id=work.id, number=1, pages=pages))
    interaction["artifact_id"] = work.id


def view(db, work):
    version = db.get(CreativeWorkVersion, (work.id, work.branch[work.cursor]))
    return {
        "artifact_id": work.id,
        "title": work.title,
        "saved": work.saved,
        "state_revision": work.revision,
        "version": version.number,
        "pages": version.pages,
        "can_undo": work.cursor > 0,
        "can_redo": work.cursor + 1 < len(work.branch),
    }


def apply(db, work, action, pages=None):
    if action == "save":
        work.saved = True
    elif action == "undo" and work.cursor > 0:
        work.cursor -= 1
    elif action == "redo" and work.cursor + 1 < len(work.branch):
        work.cursor += 1
    elif action == "revise" and pages:
        latest = db.query(func.max(CreativeWorkVersion.number)).filter_by(work_id=work.id).scalar()
        number = latest + 1
        db.add(CreativeWorkVersion(work_id=work.id, number=number, pages=pages))
        work.branch = [*work.branch[: work.cursor + 1], number]
        work.cursor += 1
    else:
        raise HTTPException(409, "version operation unavailable")
    work.revision += 1
    if work.saved and action in ("save", "revise"):
        db.add(
            OutboxEvent(
                aggregate_type="EduArtifact",
                aggregate_id=work.id,
                event_type="CreationFootprintRecorded.v1",
                payload={
                    "ward_id": work.ward_id,
                    "artifact_id": work.id,
                    "title": work.title,
                    "state_revision": work.revision,
                    "version": work.branch[work.cursor],
                },
            )
        )
    db.flush()
    return view(db, work)


def rename_saved(db, work, title: str):
    if not work.saved:
        raise HTTPException(409, "save work before renaming")
    cleaned = title.strip()
    if not cleaned or len(cleaned) > 80:
        raise HTTPException(422, "title must be 1 to 80 characters")
    work.title = cleaned
    work.revision += 1
    db.flush()
    return view(db, work)


def delete_saved(db, work):
    if not work.saved:
        raise HTTPException(409, "only saved work can be deleted")
    for table in (CreativeWorkCommand, CreativeWorkVersion):
        db.query(table).filter(table.work_id == work.id).delete(
            synchronize_session=False
        )
    db.delete(work)
    db.flush()


def temporary_cutoff():
    return now() - timedelta(hours=4)


def expire_temporary(db):
    rows = (
        db.query(CreativeWork)
        .filter(
            CreativeWork.saved.is_(False), CreativeWork.updated_at <= temporary_cutoff()
        )
        .with_for_update(skip_locked=True)
        .limit(200)
        .all()
    )
    ids = [row.id for row in rows]
    if ids:
        for table in (CreativeWorkCommand, CreativeWorkVersion):
            db.query(table).filter(table.work_id.in_(ids)).delete(
                synchronize_session=False
            )
        db.query(CreativeWork).filter(CreativeWork.id.in_(ids)).delete(
            synchronize_session=False
        )
    db.commit()
    return len(ids)
