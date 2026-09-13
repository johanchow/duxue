from .common import *

router = APIRouter(tags=["companion"])

@router.post("/companion/turn")
def companion_turn(body: CompanionTurnRequest, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    """Create or continue exactly one controlled companion domain Run.

    This foundation endpoint intentionally returns routing/context metadata only;
    the selected domain workflow will own Ward-facing streaming output.
    """
    try:
        result = CompanionCoordinator(db).handle(
            ward_id=principal.user_id,
            content=body.content,
            thread_id=body.thread_id,
            expected_thread_version=body.expected_thread_version,
            route_hint=body.route_hint,
            command_id=body.command_id,
            planning_items=body.planning_items,
            planning_confirm=body.planning_confirm,
            study_session_id=body.study_session_id,
            tutoring_directive=body.tutoring_directive,
            review_date=body.review_date,
            review_feeling=body.review_feeling,
            review_reflection=body.review_reflection,
            adopt_focus_kit=body.adopt_focus_kit,
        )
        return result.model_dump()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/companion/runs/{run_id}/cancel")
def cancel_companion_run(
    run_id: str,
    body: AgentRunCancelRequest,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    try:
        return CompanionCoordinator(db).cancel(
            ward_id=principal.user_id,
            run_id=run_id,
            command_id=body.command_id,
            expected_thread_version=body.expected_thread_version,
        ).model_dump()
    except HTTPException:
        db.rollback()
        raise


@router.get("/companion/runs/{run_id}/events")
def replay_companion_events(
    run_id: str,
    after_sequence: int = Query(default=0, ge=0),
    attempt: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    """Replay redacted events for the current or requested Run attempt.

    The client treats this as SSE replay, not a write model.  A stale attempt
    is rejected so an old handoff cannot be appended to the current UI.
    """
    run = db.get(AgentRun, run_id)
    if run is None or run.ward_id != principal.user_id:
        raise HTTPException(404, "agent run not found")
    selected_attempt = attempt or run.attempt
    if selected_attempt != run.attempt:
        raise HTTPException(409, "requested attempt is no longer current")
    events = db.query(AgentStreamEvent).filter(
        AgentStreamEvent.run_id == run_id,
        AgentStreamEvent.attempt == selected_attempt,
        AgentStreamEvent.sequence > after_sequence,
    ).order_by(AgentStreamEvent.sequence).all()

    def stream():
        for event in events:
            payload = {
                "thread_id": run.thread_id,
                "run_id": run.id,
                "attempt": selected_attempt,
                "sequence": event.sequence,
                "policy_version": event.policy_version,
                "payload": event.payload,
            }
            yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


