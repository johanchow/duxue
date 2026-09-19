from .common import *
from app.infrastructure.persistence.models import PlanDraft
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.observability.telemetry import record_companion_rejection

router = APIRouter(tags=["companion"])


def _rejection_code(error: HTTPException) -> str:
    detail = str(error.detail)
    if "thread has changed" in detail or "version 0" in detail:
        return "thread_version_conflict"
    if "交互已过期" in detail or "交互已失效" in detail or "不允许这个动作" in detail:
        return "interaction_expired"
    if "cannot be resumed" in detail:
        return "focus_run_not_resumable"
    if "command_id" in detail or "command is already" in detail:
        return "command_id_conflict"
    return "companion_request_rejected"


def _companion_attachments(ward_id: str, keys: list[str]) -> None:
    prefix = f"ward/{ward_id}/companion/"
    if any(not key.startswith(prefix) or not storage.exists(key) for key in keys):
        raise HTTPException(400, "invalid companion attachment")


@router.post("/companion/attachments/upload-url")
def companion_attachment_upload_url(
    body: UploadUrlRequest, request: Request, principal: Principal = Depends(current_ward),
):
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"} or not body.content_type.startswith("image/"):
        raise HTTPException(400, "unsupported companion attachment")
    key = f"ward/{principal.user_id}/companion/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@router.get("/companion/threads/{thread_id}/messages")
def companion_messages(
    thread_id: str,
    before_thread_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    thread = db.get(ConversationThread, thread_id)
    if thread is None or thread.ward_id != principal.user_id:
        raise HTTPException(404, "conversation thread not found")
    query = db.query(CompanionMessage).filter_by(thread_id=thread_id, ward_id=principal.user_id)
    if before_thread_version is not None:
        query = query.filter(CompanionMessage.thread_version < before_thread_version)
    rows = query.order_by(CompanionMessage.thread_version.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [{
        "id": row.id, "thread_id": row.thread_id, "run_id": row.run_id,
        "turn_id": row.turn_id, "attempt": row.attempt, "command_id": row.command_id,
        "thread_version": row.thread_version, "author_type": row.author_type,
        "content": row.content, "attachment_refs": row.attachment_refs,
        "interaction_ref": row.interaction_ref, "created_at": row.created_at,
    } for row in reversed(rows)]
    return {
        "thread_id": thread.id, "thread_version": thread.version, "messages": messages,
        "next_before_thread_version": rows[-1].thread_version if has_more and rows else None,
    }

@router.post("/companion/turn")
def companion_turn(body: CompanionTurnRequest, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    """Create or continue exactly one controlled companion domain Run.

    This foundation endpoint intentionally returns routing/context metadata only;
    the selected domain workflow will own Ward-facing streaming output.
    """
    try:
        _companion_attachments(principal.user_id, body.attachment_keys)
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
            attachment_keys=body.attachment_keys,
            structured_command=body.structured_command.model_dump() if body.structured_command else None,
        )
        return result.model_dump()
    except HTTPException as error:
        if error.status_code == 409:
            record_companion_rejection(
                code=_rejection_code(error), status_code=error.status_code,
                has_thread=body.thread_id is not None,
                has_structured_command=body.structured_command is not None,
            )
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.get("/companion/planning/drafts/{draft_id}")
def companion_plan_draft(draft_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    """Target Context query used by a plan_confirm_list interaction."""
    draft = db.get(PlanDraft, draft_id)
    if draft is None or draft.ward_id != principal.user_id:
        raise HTTPException(404, "计划草稿不存在")
    return PlanningDomainService(db).plan_draft_view(principal.user_id, draft_id)


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
