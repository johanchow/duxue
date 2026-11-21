from .common import *
from contextlib import suppress
from app.infrastructure.ai.asr import DisplayTranscript, MessageAsr

router = APIRouter(tags=["system"])
_asr_logger = logging.getLogger("duxue.asr")

@router.on_event("startup")
def startup() -> None:
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/telemetry/client-events", status_code=202)
def relay_mobile_telemetry(
    body: ClientTelemetryBatch,
    principal: Principal = Depends(current_guardian_or_ward),
):
    trace.get_current_span().set_attribute("duxue.component", "telemetry-relay")
    if not allow_batch(principal.user_id, len(body.events)):
        raise HTTPException(429, "telemetry rate limit exceeded")
    try:
        return {"accepted": relay_client_telemetry(body.events)}
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.websocket("/ws/asr/transcribe")
async def transcribe_voice(websocket: WebSocket) -> None:
    """Authenticate a Guardian or Ward and relay one hold-to-talk turn."""
    db = SessionLocal()
    provider = None
    forward_task = None
    display_session = None
    try:
        # Accept first so an authentication failure is a structured, actionable
        # protocol event rather than an opaque client-side handshake exception.
        await websocket.accept()
        authorization = websocket.headers.get("authorization")
        try:
            principal = current_guardian_or_ward(authorization, db)
        except HTTPException as error:
            auth_scheme = "missing"
            if authorization:
                auth_scheme = authorization.split(" ", 1)[0].lower()
            attrs = {
                "asr.stage": "auth",
                "asr.has_authorization": bool(authorization),
                "asr.auth_scheme": auth_scheme,
                "asr.reason": str(error.detail),
            }
            _asr_logger.warning("asr.ws.auth_rejected", extra={"telemetry": attrs})
            record_asr_session(result="rejected", stage="auth")
            await websocket.send_json({
                "type": "error",
                "code": "unauthorized",
                "message": "登录已过期，请重新登录",
            })
            await websocket.close(code=1008)
            return
        db.close()  # Authentication is complete; release the pooled connection during recording.
        _asr_logger.info("asr.ws.accepted", extra={"telemetry": {"principal.role": principal.role}})
        start = await websocket.receive_json()
        if start.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "start is required"})
            await websocket.close(code=1008)
            return

        message_model = settings.asr_model.startswith("qwen-audio-3.1-asr-flash-message")
        provider = await (MessageAsr.connect() if message_model else DashscopeRealtimeAsr.connect())
        if message_model and start.get("display_transcript") is True:
            display_session = DisplayTranscript()

        async def send_result(event):
            if display_session and event["type"] == "final" and event.get("text"):
                display = await display_session.result()
                if display and len(display) <= 4000:
                    event = {**event, "display_text": display}
            await websocket.send_json(event)

        total_bytes = 0
        deadline = asyncio.get_running_loop().time() + settings.asr_max_record_seconds + 2
        await websocket.send_json({"type": "ready", "max_seconds": settings.asr_max_record_seconds})
        hold = AsrHold()
        forward_task = asyncio.create_task(forward_asr_events(provider, send_result, hold))
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=deadline - asyncio.get_running_loop().time())
            except TimeoutError:
                await websocket.send_json({"type": "error", "message": "recording exceeded the maximum duration"})
                return
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                total_bytes += len(chunk)
                if total_bytes > (settings.asr_max_record_seconds + 1) * 32000:
                    await websocket.send_json({"type": "error", "message": "recording too long"})
                    return
                if display_session:
                    display_session.append(chunk)
                hold.note_audio()
                await provider.send_audio(message["bytes"])
                continue
            if message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "cancel":
                    record_asr_session(result="cancelled", stage="recording", role=principal.role)
                    return
                if command.get("type") == "commit":
                    if display_session:
                        display_session.commit()
                    outcome = None
                    ready = hold.commit()
                    if not hold.finished:
                        if forward_task.done():
                            ready = hold.unfinished_final()
                        else:
                            await provider.commit()
                            outcome = await asyncio.wait_for(forward_task, timeout=15)
                            if not hold.finished:
                                ready = hold.unfinished_final()
                    for item in ready:
                        await send_result(item)
                    success = (ready[-1]["type"] if ready else outcome) == "final"
                    record_asr_session(result="success" if success else "error", stage="completed" if success else "provider", role=principal.role)
                    return
                await websocket.send_json({"type": "error", "message": "unsupported ASR command"})
                return
    except (WebSocketDisconnect, asyncio.CancelledError):
        record_asr_session(result="cancelled", stage="transport")
        return
    except AsrConfigurationError as error:
        _asr_logger.warning("asr.ws.configuration_error", extra={"telemetry": {"asr.stage": "provider", "asr.reason": str(error)}})
        record_asr_session(result="error", stage="configuration")
        await websocket.send_json({"type": "error", "code": "configuration", "message": str(error)})
    except Exception:
        _asr_logger.exception("asr.ws.failed", extra={"telemetry": {"asr.stage": "provider"}})
        record_asr_session(result="error", stage="provider")
        await websocket.send_json({"type": "error", "code": "unavailable", "message": "voice transcription is temporarily unavailable"})
    finally:
        if forward_task:
            forward_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await forward_task
        if display_session:
            await display_session.close()
        if provider:
            with suppress(Exception):
                await provider.finish()
            with suppress(Exception):
                await provider.close()
        db.close()

