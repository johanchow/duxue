"""Run side-effect-free domain checks before writes and final delivery."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from threading import BoundedSemaphore

from app.infrastructure.observability.telemetry import edu_agent_span


_workers = ThreadPoolExecutor(max_workers=8, thread_name_prefix="edu-gate")
_slots = BoundedSemaphore(8)


class GateRunner:
    def __init__(self, handlers=None, *, timeout_seconds=2.0):
        self.handlers = dict(handlers or {})
        self.timeout_seconds = timeout_seconds

    def allows(self, required, *, phase, candidate):
        for gate in sorted(required):
            with edu_agent_span("check", gate, **{"agent.phase": phase}) as span:
                allowed = self._check(self.handlers.get(gate), phase, candidate)
                span.set_attribute("agent.gate.allowed", allowed)
                if not allowed:
                    return False
        return True

    def _check(self, handler, phase, candidate):
        if handler is None or not _slots.acquire(blocking=False):
            return False
        try:
            work = _workers.submit(copy_context().run, handler, phase, candidate)
        except RuntimeError:
            _slots.release()
            return False
        work.add_done_callback(lambda _: _slots.release())
        try:
            return work.result(timeout=self.timeout_seconds) is True
        except TimeoutError:
            work.cancel()
            return False
        except Exception:
            return False
