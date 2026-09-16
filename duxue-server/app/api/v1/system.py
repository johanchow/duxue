from .common import *

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
    """Authenticate a Guardian and proxy one hold-to-talk turn to DashScope."""
    db = SessionLocal()
    provider = None
    forward_task = None
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
        _asr_logger.info("asr.ws.accepted", extra={"telemetry": {"principal.role": principal.role}})
        start = await websocket.receive_json()
        if start.get("type") != "start":
            await websocket.send_json({"type": "error", "message": "start is required"})
            await websocket.close(code=1008)
            return

        provider = await DashscopeRealtimeAsr.connect()
        await websocket.send_json({"type": "ready", "max_seconds": settings.asr_max_record_seconds})
        forward_task = asyncio.create_task(forward_asr_events(provider, websocket.send_json))
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=settings.asr_max_record_seconds)
            except TimeoutError:
                await websocket.send_json({"type": "error", "message": "recording exceeded the maximum duration"})
                return
            if message.get("bytes") is not None:
                await provider.send_audio(message["bytes"])
                continue
            if message.get("text"):
                command = json.loads(message["text"])
                if command.get("type") == "cancel":
                    record_asr_session(result="cancelled", stage="recording", role=principal.role)
                    return
                if command.get("type") == "commit":
                    await provider.commit()
                    outcome = await forward_task
                    record_asr_session(
                        result="success" if outcome == "final" else "error",
                        stage="completed" if outcome == "final" else "provider",
                        role=principal.role,
                    )
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
        if forward_task and not forward_task.done():
            forward_task.cancel()
        if provider:
            await provider.finish()
            await provider.close()
        db.close()

