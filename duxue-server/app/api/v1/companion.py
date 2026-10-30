from .common import *
from app.api.schemas import CompanionHistoryClearRequest
from app.application.commands.companion_history import clear_history, history_is_visible, visible_threads
from uuid import UUID
from app.infrastructure.persistence.models import PlanDraft
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.infrastructure.observability.telemetry import record_companion_rejection

router = APIRouter(tags=["companion"])


_REJECTION_CODES = {
    "开始时间格式无效": "invalid_start_at",
    "计划开始时间格式无效": "invalid_start_at",
    "预计时长必须为 1 到 480 分钟": "invalid_planned_minutes",
    "请选择当前问题中的任务": "invalid_target_task",
    "请从当前候选名称中明确选择任务": "invalid_target_task",
    "请从当前同名任务中明确选择": "invalid_title_conflict",
    "请补充有效任务名字": "invalid_title",
    "标题冲突需要明确选择": "invalid_title_conflict",
    "标题冲突选项已失效": "invalid_title_conflict",
    "请选择当前标题对应的任务": "invalid_title_conflict",
    "不支持的澄清字段": "unsupported_clarification_field",
    "必做任务暂不安排需要说明原因": "defer_reason_required",
    "未知计划操作": "unknown_plan_operation",
    "invalid companion attachment": "invalid_attachment",
}


def _rejection_code(error: HTTPException) -> str:
    detail = error.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return detail["code"]
    text = detail if isinstance(detail, str) else str(detail)
    if text in _REJECTION_CODES:
        return _REJECTION_CODES[text]
    if "thread has changed" in text or "version 0" in text:
        return "thread_version_conflict"
    if "交互已过期" in text or "交互已失效" in text or "不允许这个动作" in text:
        return "interaction_expired"
    if "cannot be resumed" in text:
        return "focus_run_not_resumable"
    if "command_id" in text or "command is already" in text:
        return "command_id_conflict"
    return "companion_request_rejected"


def _valid_companion_attachment_key(ward_id: str, key: object) -> bool:
    prefix = f"ward/{ward_id}/companion/"
    return (
        isinstance(key, str)
        and key.startswith(prefix)
        and bool(key[len(prefix):])
        and "/" not in key[len(prefix):]
        and "\\" not in key[len(prefix):]
    )


def _companion_attachments(ward_id: str, keys: list[str]) -> None:
    if any(not _valid_companion_attachment_key(ward_id, key) or not storage.exists(key) for key in keys):
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


@router.get("/companion/messages/{message_id}/attachments/{index}")
def companion_message_image(
    message_id: str,
    index: int,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    try:
        UUID(message_id)
    except ValueError:
        raise HTTPException(404, "companion image not found") from None
    message = db.get(CompanionMessage, message_id)
    if message is None or message.ward_id != principal.user_id or message.author_type != "ward":
        raise HTTPException(404, "companion image not found")
    if not history_is_visible(db, principal.user_id, message.thread_id):
        raise HTTPException(404, "companion image not found")
    refs = message.attachment_refs or []
    if index < 0 or index >= len(refs):
        raise HTTPException(404, "companion image not found")
    key = refs[index]
    suffix = key.rsplit(".", 1)[-1].lower() if isinstance(key, str) else ""
    media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    if not _valid_companion_attachment_key(principal.user_id, key) or suffix not in media_types:
        raise HTTPException(404, "companion image not found")
    if not storage.exists(key):
        raise HTTPException(404, "companion image not found")
    try:
        content = storage.read_bytes(key)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "companion image not found") from None
    return Response(content=content, media_type=media_types[suffix], headers={"Cache-Control": "private, max-age=300"})


def _serialize_message(row: CompanionMessage) -> dict:
    return {
        "id": row.id, "thread_id": row.thread_id, "run_id": row.run_id,
        "turn_id": row.turn_id, "attempt": row.attempt, "command_id": row.command_id,
        "thread_version": row.thread_version, "author_type": row.author_type,
        "content": row.content, "attachment_refs": row.attachment_refs,
        "interaction_ref": row.interaction_ref, "created_at": row.created_at,
    }


def _previous_thread_with_messages(db: Session, ward_id: str, current_thread: ConversationThread) -> ConversationThread | None:
    candidates = (
        visible_threads(db, ward_id)
        .filter(
            ConversationThread.ward_id == ward_id,
            ConversationThread.id != current_thread.id,
            ConversationThread.created_at <= current_thread.created_at,
        )
        .order_by(ConversationThread.created_at.desc(), ConversationThread.id.desc())
        .all()
    )
    for item in candidates:
        if item.created_at == current_thread.created_at and item.id >= current_thread.id:
            continue
        has_msg = (
            db.query(CompanionMessage.id)
            .filter_by(thread_id=item.id, ward_id=ward_id)
            .first()
        )
        if has_msg is not None:
            return item
    return None


def _thread_messages_payload(
    db: Session,
    *,
    ward_id: str,
    thread: ConversationThread,
    before_thread_version: int | None,
    limit: int,
) -> dict:
    query = db.query(CompanionMessage).filter_by(thread_id=thread.id, ward_id=ward_id)
    if before_thread_version is not None:
        query = query.filter(CompanionMessage.thread_version < before_thread_version)
    rows = query.order_by(CompanionMessage.thread_version.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    messages = [_serialize_message(row) for row in reversed(rows)]
    next_before = rows[-1].thread_version if has_more and rows else None
    previous_thread_id: str | None = None
    if next_before is None:
        prev = _previous_thread_with_messages(db, ward_id, thread)
        if prev is not None:
            previous_thread_id = prev.id
    return {
        "thread_id": thread.id,
        "thread_version": thread.version,
        "messages": messages,
        "next_before_thread_version": next_before,
        "previous_thread_id": previous_thread_id,
    }


@router.get("/companion/threads/current/messages")
def current_companion_messages(
    before_thread_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    latest_msg = (
        db.query(CompanionMessage)
        .join(ConversationThread, ConversationThread.id == CompanionMessage.thread_id)
        .join(Ward, Ward.id == CompanionMessage.ward_id)
        .filter(CompanionMessage.ward_id == principal.user_id, ConversationThread.history_generation == Ward.history_generation)
        .order_by(CompanionMessage.created_at.desc(), CompanionMessage.thread_version.desc())
        .first()
    )
    thread = db.get(ConversationThread, latest_msg.thread_id) if latest_msg is not None else None
    if thread is None:
        thread = (
            visible_threads(db, principal.user_id)
            .order_by(ConversationThread.updated_at.desc(), ConversationThread.created_at.desc())
            .first()
        )
    if thread is None:
        return {
            "thread_id": None,
            "thread_version": 0,
            "messages": [],
            "next_before_thread_version": None,
            "previous_thread_id": None,
        }
    return _thread_messages_payload(
        db,
        ward_id=principal.user_id,
        thread=thread,
        before_thread_version=before_thread_version,
        limit=limit,
    )


@router.get("/companion/threads/{thread_id}/messages")
def companion_messages(
    thread_id: str,
    before_thread_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    thread = visible_threads(db, principal.user_id).filter(ConversationThread.id == thread_id).first()
    if thread is None:
        raise HTTPException(404, "conversation thread not found")
    return _thread_messages_payload(
        db,
        ward_id=principal.user_id,
        thread=thread,
        before_thread_version=before_thread_version,
        limit=limit,
    )

@router.post("/companion/history/clear")
def clear_companion_history(
    body: CompanionHistoryClearRequest,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    try:
        return clear_history(db, ward_id=principal.user_id, command_id=body.command_id)
    except Exception:
        db.rollback()
        raise


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
            tutoring_intent=body.tutoring_intent,
            review_date=body.review_date,
            review_feeling=body.review_feeling,
            review_reflection=body.review_reflection,
            attachment_keys=body.attachment_keys,
            structured_command=body.structured_command.model_dump() if body.structured_command else None,
        )
        return result.model_dump()
    except HTTPException as error:
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
    if not history_is_visible(db, principal.user_id, run.thread_id):
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
