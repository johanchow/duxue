from app.application.queries.ward_messages import chat_messages, readable_reply, thread_messages_payload
from app.api.deps import expose_turn_trace
from app.api.reply_events import GUIDE_STAGES, stream_reply
from .common import (
    APIRouter,
    AgentRun,
    AgentRunCancelRequest,
    AgentStreamEvent,
    CompanionCoordinator,
    CompanionMessage,
    CompanionTurnRequest,
    ConversationThread,
    Depends,
    HTTPException,
    Principal,
    Query,
    Request,
    Response,
    Session,
    StreamingResponse,
    UploadUrlRequest,
    Ward,
    current_ward,
    datetime,
    get_db,
    json,
    secrets,
    settings,
    storage,
    timezone,
)
from app.api.schemas import CompanionHistoryClearRequest
from app.application.commands.companion_history import clear_history, history_is_visible, visible_threads
from contextlib import aclosing
import re
from uuid import UUID
from app.infrastructure.ai.speech_task import tutor_audio, tutor_audio_frames
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
    if message is None or message.ward_id != principal.user_id:
        raise HTTPException(404, "companion image not found")
    if not history_is_visible(db, principal.user_id, message.thread_id) or message.thread_version <= db.get(ConversationThread, message.thread_id).clear_version:
        raise HTTPException(404, "companion image not found")
    refs = message.attachment_refs or []
    if index < 0 or index >= len(refs):
        raise HTTPException(404, "companion image not found")
    key = refs[index]
    suffix = key.rsplit(".", 1)[-1].lower() if isinstance(key, str) else ""
    media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    valid = message.author_type == "ward" and _valid_companion_attachment_key(principal.user_id, key)
    if message.author_type == "companion" and isinstance(key, str):
        prefix = f"ward/{principal.user_id}/search-photos/"
        valid = key.startswith(prefix) and re.fullmatch(r"[0-9a-f]{64}\.jpg", key[len(prefix):]) is not None
    if not valid or suffix not in media_types:
        raise HTTPException(404, "companion image not found")
    if not storage.exists(key):
        raise HTTPException(404, "companion image not found")
    try:
        content = storage.read_bytes(key)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "companion image not found") from None
    return Response(content=content, media_type=media_types[suffix], headers={"Cache-Control": "private, max-age=300"})


@router.get("/companion/messages/{message_id}/speech")
async def companion_message_speech(message_id: UUID, stream: bool = False, principal: Principal = Depends(current_ward),
                                   db: Session = Depends(get_db)):
    row = chat_messages(db).filter(CompanionMessage.id == str(message_id), CompanionMessage.ward_id == principal.user_id).one_or_none()
    if row is None or not history_is_visible(db, principal.user_id, row.thread_id) or row.thread_version <= db.get(ConversationThread, row.thread_id).clear_version:
        raise HTTPException(404, "reply unavailable")
    if not readable_reply(row):
        raise HTTPException(404, "reply unavailable")
    text = row.content
    db.rollback()  # Release the read transaction before waiting on synthesis.
    try:
        if stream:
            frames = tutor_audio_frames(text)
            first = await anext(frames)

            async def body():
                async with aclosing(frames):
                    yield first
                    async for frame in frames:
                        yield frame

            return StreamingResponse(body(), media_type="audio/mpeg",
                                     headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
        audio = await tutor_audio(text)
    except Exception as error:
        raise HTTPException(503, "朗读服务暂不可用") from error
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.get("/companion/threads/current/messages")
def current_companion_messages(
    before_thread_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    latest_msg = (
        chat_messages(db)
        .join(ConversationThread, ConversationThread.id == CompanionMessage.thread_id)
        .join(Ward, Ward.id == CompanionMessage.ward_id)
        .filter(CompanionMessage.ward_id == principal.user_id, ConversationThread.history_generation == Ward.history_generation,
                ConversationThread.deleted.is_(False), CompanionMessage.thread_version > ConversationThread.clear_version)
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
    return thread_messages_payload(
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
    return thread_messages_payload(
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


@router.post("/companion/turn", dependencies=[Depends(expose_turn_trace)])
def companion_turn(
    body: CompanionTurnRequest, request: Request, response: Response,
    principal: Principal = Depends(current_ward), db: Session = Depends(get_db),
):
    """Create or continue exactly one controlled companion domain Run."""
    def invoke(db):
        try:
            _companion_attachments(principal.user_id, body.attachment_keys)
            result = CompanionCoordinator(db).handle(
                ward_id=principal.user_id,
                content=body.content,
                voice_display_text=body.voice_display_text,
                thread_id=body.thread_id,
                expected_thread_version=body.expected_thread_version,
                route_hint=body.route_hint,
                command_id=body.command_id,
                study_session_id=body.study_session_id,
                tutoring_directive=body.tutoring_directive,
                tutoring_intent=body.tutoring_intent,
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

    if "text/event-stream" in request.headers.get("accept", ""):
        bind = db.get_bind()
        db.close()

        def invoke_stream():
            with Session(bind, expire_on_commit=False) as worker_db:
                return invoke(worker_db)

        return stream_reply(invoke_stream, response, stages=GUIDE_STAGES, error_code="companion_error")
    return invoke(db)

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
    cutoff = db.get(ConversationThread, run.thread_id).clear_version
    if cutoff and not db.query(CompanionMessage.id).filter(
        CompanionMessage.run_id == run.id, CompanionMessage.thread_version > cutoff
    ).first():
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
