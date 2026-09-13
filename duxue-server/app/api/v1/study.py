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
    active = _open_session(db, task_id=item.id)
    if active: return active
    row = StudySession(ward_id=principal.user_id, task_id=item.id); item.status="active"; db.add(row); db.flush(); db.add(StudySessionInterval(study_session_id=row.id))
    publish_learning_fact(db, ward_id=row.ward_id, event_type="study_session.started", source_type="study_session", source_id=row.id, payload={"task_id": row.task_id})
    db.commit(); return {"id": row.id, "status": row.status, "active_seconds": 0}


@router.post("/assignments/{assignment_id}/sessions", status_code=201)
def start_assignment_session(assignment_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    assignment = db.get(Task, assignment_id)
    if assignment is None or assignment.ward_id != principal.user_id or assignment.status == "completed": raise HTTPException(404, "assignment not found")
    active = _open_session(db, task_id=assignment.id)
    if active: return active
    row = StudySession(ward_id=principal.user_id, task_id=assignment.id); assignment.status="active"; db.add(row); db.flush(); db.add(StudySessionInterval(study_session_id=row.id))
    publish_learning_fact(db, ward_id=row.ward_id, event_type="study_session.started", source_type="study_session", source_id=row.id, payload={"task_id": row.task_id})
    db.commit(); return {"id": row.id, "status": row.status, "active_seconds": 0}


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "paused": raise HTTPException(404, "paused session not found")
    session.status="active"; session.version += 1; session.last_activity_at=now()
    db.get(Task, session.task_id).status="active"; db.add(StudySessionInterval(study_session_id=session.id))
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.resumed", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id})
    db.commit(); return {"id": session.id, "status": session.status, "active_seconds": session.active_seconds}


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, body: SessionPause, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id or session.status != "active": raise HTTPException(404, "active session not found")
    interval = db.query(StudySessionInterval).filter_by(study_session_id=session.id, ended_at=None).one()
    interval.ended_at=now(); interval.end_reason="paused"; interval.active_seconds=max(0, body.active_seconds-session.active_seconds)
    session.status="paused"; session.active_seconds=body.active_seconds; session.pause_count += 1; session.version += 1; session.last_activity_at=interval.ended_at
    db.get(Task, session.task_id).status="paused"
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.paused", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id, "active_seconds": session.active_seconds})
    db.commit(); return {"id": session.id, "status": session.status, "active_seconds": session.active_seconds}

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
    db.add(TutoringMessage(tutoring_session_id=tutoring_session.id, role="assistant", content=answer, hint_level=1)); db.commit(); return {"role": "assistant", "content": answer, "mode": "socratic"}

@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: str, body: SessionFinish, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    session = db.get(StudySession, session_id)
    if session is None or session.ward_id != principal.user_id: raise HTTPException(404, "session not found")
    if session.status not in ("active", "paused"): raise HTTPException(409, "session is already completed")
    if session.status == "active":
        interval = db.query(StudySessionInterval).filter_by(study_session_id=session.id, ended_at=None).one()
        interval.ended_at=now(); interval.end_reason="completed"; interval.active_seconds=max(0, body.active_seconds-session.active_seconds)
    session.status="completed"; session.ended_at=now(); session.active_seconds=body.active_seconds; session.completion_reason="ward_finished"; session.version += 1
    db.get(Task, session.task_id).status="completed"
    publish_learning_fact(db, ward_id=session.ward_id, event_type="study_session.completed", source_type="study_session", source_id=session.id, source_version=session.version, payload={"task_id": session.task_id, "active_seconds": session.active_seconds})
    db.commit(); return {"status": "completed"}

