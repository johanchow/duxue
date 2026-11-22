"""Transport for public conversation stages and the checked final reply."""
import asyncio
import json
import logging
from threading import Event

from fastapi import HTTPException, Response
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.agent_specs.runtime import node_started

logger = logging.getLogger(__name__)

GUIDE_STAGES = {
    "companion.route": "route",
    "companion.planning": "plan",
    "companion.reflection": "reflect",
    "tutoring.attempt": "draft",
    "tutoring.exit_gate": "check",
    "tutoring.revise": "revise",
    "tutoring.recheck": "recheck",
}


def stream_reply(invoke, response: Response, *, stages, error_code):
    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        closed = Event()

        def progress(node):
            stage = stages.get(node)
            if stage and not closed.is_set():
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, ("stage", stage))
                except RuntimeError:
                    # The HTTP event loop can close before the worker finishes.
                    if not loop.is_closed():
                        raise

        async def run():
            token = node_started.set(progress)
            try:
                await queue.put(("result", jsonable_encoder(await run_in_threadpool(invoke))))
            except HTTPException as exc:
                await queue.put(("error", {"status": exc.status_code, "detail": jsonable_encoder(exc.detail)}))
            except Exception:
                logger.exception("Conversation turn failed")
                await queue.put(("error", {"status": 500, "detail": {"code": error_code}}))
            finally:
                node_started.reset(token)

        worker = asyncio.create_task(run())
        previous = None
        try:
            while True:
                kind, value = await queue.get()
                if kind == "stage" and value == previous:
                    continue
                previous = value
                yield "data: " + json.dumps({"type": kind, "value": value}, ensure_ascii=False) + "\n\n"
                if kind != "stage":
                    break
        finally:
            closed.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={**dict(response.headers), "Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
