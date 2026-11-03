from fastapi.responses import Response

from app.application.commands.start_cue import StartCueService
from app.application.queries.pronunciation_speech import PronunciationLessonQuery
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.contexts.study.domain.execution import can_finish
from app.contexts.study.domain.start_cue import StartCueError

from .common import *

router = APIRouter(tags=["study"])

def _open_session(db: Session, *, task_id: str) -> dict | None:
    query = db.query(StudySession).filter(StudySession.status.in_(("active", "paused"))).filter_by(task_id=task_id)
    row = query.order_by(StudySession.started_at.desc()).first()
    return None if row is None else {"id": row.id, "status": row.status, "active_seconds": row.active_seconds}

@router.post("/plan-items/{item_id}/sessions", status_code=201)
def start_session(item_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    item = db.get(Task, item_id); plan = db.get(DailySchedule, item.schedule_id) if item and item.schedule_id else None
    if plan is None or plan.ward_id != principal.user_id: raise HTTPException(404, "plan task not found")
    from app.application.commands.task_execution import TaskExecutionService
    result = TaskExecutionService(db).execute(principal.user_id, item.id, "start")
    StartCueService(db).note_task_started(principal.user_id, item.id)
    db.commit()
    return result["session"]


@router.post("/assignments/{assignment_id}/sessions", status_code=201)
def start_assignment_session(assignment_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    assignment = db.get(Task, assignment_id)
    if assignment is None or assignment.ward_id != principal.user_id or assignment.status == "completed": raise HTTPException(404, "assignment not found")
    from app.application.commands.task_execution import TaskExecutionService
    result = TaskExecutionService(db).execute(principal.user_id, assignment.id, "start")
    StartCueService(db).note_task_started(principal.user_id, assignment.id)
    db.commit()
    return result["session"]


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "paused": raise HTTPException(404, "paused session not found")
    from app.application.commands.task_execution import TaskExecutionService
    result = TaskExecutionService(db).execute(principal.user_id, session.task_id, "resume")
    db.commit()
    return result["session"]


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, body: SessionPause, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "active": raise HTTPException(404, "active session not found")
    from app.application.commands.task_execution import TaskExecutionService
    result = TaskExecutionService(db).execute(principal.user_id, session.task_id, "pause")
    db.commit()
    return result["session"]

@router.post("/sessions/{session_id}/messages")
def tutor(session_id: str, body: MessageCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    tutoring_session = db.query(TutoringSession).filter_by(study_session_id=session_id).one_or_none()
    if tutoring_session is None:
        tutoring_session = TutoringSession(ward_id=session.ward_id, study_session_id=session_id, question_summary=body.content, model_name="fallback-socratic-v1")
        db.add(tutoring_session); db.flush()
    question = TutoringMessage(tutoring_session_id=tutoring_session.id, role="ward", content=body.content, is_stuck_point=True)
    db.add(question); db.flush()
    publish_learning_fact(db, ward_id=session.ward_id, event_type="tutoring.stuck_point_recorded", source_type="tutoring_message", source_id=question.id, payload={"study_session_id": session.id, "tutoring_session_id": tutoring_session.id})
    # Model routing remains injectable; this safe fallback keeps an unavailable provider from blocking study.
    answer = "先别急着找答案。你能说说题目已知什么、要解决什么吗？把第一步写出来，我们一起检查。"
    db.add(TutoringMessage(tutoring_session_id=tutoring_session.id, role="assistant", content=answer)); db.commit(); return {"role": "assistant", "content": answer, "mode": "socratic"}

@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: str, body: SessionFinish, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    if session.status not in ("active", "paused"): raise HTTPException(409, "session is already completed")
    if not can_finish(session.task_id): raise HTTPException(409, "a taskless session cannot be finished as a task")
    from app.application.commands.task_execution import TaskExecutionService
    result = TaskExecutionService(db).execute(principal.user_id, session.task_id, "complete")
    db.commit()
    return {"status":result["status"]}


def _cue_error(error: StartCueError) -> HTTPException:
    status = 404 if error.code == "not_found" else 409
    return HTTPException(status, error.code)


@router.get("/start-cues/current")
def current_start_cue(principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    try:
        view = StartCueService(db).sync(principal.user_id)
    except StartCueError as error:
        raise _cue_error(error) from error
    db.commit()
    return view


@router.get("/pronunciation-lessons/{lesson_ref}")
def get_pronunciation_lesson(lesson_ref: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    return PronunciationLessonQuery(db).get(ward_id=principal.user_id, lesson_ref=lesson_ref)


@router.get("/pronunciation-lessons/{lesson_ref}/speech")
def speak_pronunciation_lesson(
    lesson_ref: str, rate: float, principal: Principal = Depends(current_ward), db: Session = Depends(get_db),
):
    audio = PronunciationLessonQuery(db).speak(ward_id=principal.user_id, lesson_ref=lesson_ref, rate=rate)
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/start-cues/{cue_id}/commands")
def act_on_start_cue(cue_id: str, body: StartCueCommand, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    try:
        view = StartCueService(db).act(principal.user_id, cue_id, body.command, body.expected_version)
    except StartCueError as error:
        raise _cue_error(error) from error
    db.commit()
    return view



# Explicit Ward actions; a plan confirmation never invokes these commands.
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field
from app.application.commands.sprint import SprintService


class SprintCreate(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=300)
    target_minutes: int = Field(ge=1, le=180, strict=True)
    task_id: str | None = None
    study_session_id: str | None = None
    planned_start_at: datetime | None = None
    action: Literal["create", "prepare"]


class SprintAction(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=100)
    action: Literal["start", "pause", "resume", "end", "cancel", "claim_notice"]
    expected_version: int = Field(ge=1)


@router.get("/sprints/current")
def current_sprint(principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    view = SprintService(db).current(principal.user_id)
    db.commit()
    return view


@router.post("/sprints", status_code=201)
def create_sprint(body: SprintCreate, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    try:
        result = SprintService(db).execute(principal.user_id, **body.model_dump())
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post("/sprints/{sprint_id}/commands")
def sprint_action(sprint_id: str, body: SprintAction, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    try:
        result = SprintService(db).execute(principal.user_id, sprint_id=sprint_id, **body.model_dump())
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


class TaskExecutionAction(BaseModel):
    action: Literal["start", "pause", "resume", "end", "complete", "time"]


@router.post("/assignments/{assignment_id}/commands")
def task_execution(assignment_id: str, body: TaskExecutionAction, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    from app.application.commands.task_execution import TaskExecutionService
    try:
        result = TaskExecutionService(db).execute(principal.user_id, assignment_id, body.action)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
