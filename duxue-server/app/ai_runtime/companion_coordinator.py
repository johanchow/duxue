from __future__ import annotations

from time import perf_counter

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..memory import SqlAlchemyMemoryFacade
from ..models import AgentRun, AgentTrace, ConversationThread, now, uid
from .context_builder import ContextBuilder
from .contracts import CoordinatorResult, RouteDecision
from .intent_router import IntentRouter
from .planning_adapter import PlanningWorkflowAdapter

_ACTIVE_STATUSES = ("active", "waiting_for_ward", "paused")


class CompanionCoordinator:
    """Deterministic entrypoint; it never produces a domain-model response."""

    def __init__(self, db: Session, router: IntentRouter | None = None):
        self.db = db
        self.router = router or IntentRouter()
        self.context_builder = ContextBuilder(SqlAlchemyMemoryFacade(db))

    def _thread(
        self, *, ward_id: str, thread_id: str | None, expected_version: int | None
    ) -> ConversationThread:
        if thread_id is None:
            if expected_version not in {None, 0}:
                raise HTTPException(409, "new thread must use version 0")
            thread = ConversationThread(ward_id=ward_id)
            self.db.add(thread)
            self.db.flush()
            return thread
        thread = self.db.get(ConversationThread, thread_id)
        if thread is None or thread.ward_id != ward_id:
            raise HTTPException(404, "conversation thread not found")
        if expected_version is not None and thread.version != expected_version:
            raise HTTPException(
                409, "conversation thread has changed; refresh before retrying"
            )
        return thread

    def _focus_run(self, thread: ConversationThread) -> AgentRun | None:
        if not thread.focus_run_ref:
            return None
        run = (
            self.db.query(AgentRun)
            .filter_by(
                thread_id=thread.id,
                run_ref=thread.focus_run_ref,
            )
            .one_or_none()
        )
        return run if run and run.status in _ACTIVE_STATUSES else None

    def _start_or_resume(
        self,
        *,
        thread: ConversationThread,
        decision: RouteDecision,
        focus_run: AgentRun | None,
    ) -> AgentRun:
        if decision.mode == "continue" and focus_run is not None:
            focus_run.last_active_at = now()
            return focus_run
        if focus_run is not None and focus_run.status in _ACTIVE_STATUSES:
            focus_run.status = "paused"
        run_id = uid()
        run = AgentRun(
            id=run_id,
            thread_id=thread.id,
            ward_id=thread.ward_id,
            agent_type=decision.target,
            run_ref=f"agent_run:{run_id}",
        )
        self.db.add(run)
        self.db.flush()
        thread.focus_run_ref = run.run_ref
        return run

    def _trace(
        self,
        *,
        thread: ConversationThread,
        run: AgentRun | None,
        decision: RouteDecision,
        snapshot: dict,
        duration_ms: int,
    ) -> None:
        self.db.add(
            AgentTrace(
                thread_id=thread.id,
                run_id=run.id if run else None,
                route_target=decision.target,
                route_mode=decision.mode,
                route_reason=decision.route_reason,
                context_refs=decision.context_refs,
                context_snapshot=snapshot,
                outcome={"run_status": run.status if run else None},
                duration_ms=duration_ms,
            )
        )

    def handle(
        self,
        *,
        ward_id: str,
        content: str,
        thread_id: str | None,
        expected_thread_version: int | None,
        route_hint: str | None,
        planning_items: list[dict] | None = None,
        planning_confirm: bool = False,
    ) -> CoordinatorResult:
        started = perf_counter()
        thread = self._thread(
            ward_id=ward_id,
            thread_id=thread_id,
            expected_version=expected_thread_version,
        )
        focus_run = self._focus_run(thread)
        decision = self.router.decide(
            content=content, route_hint=route_hint, focus_run=focus_run
        )
        if (
            decision.mode == "start"
            and focus_run is not None
            and decision.target not in {"clarify", "safety"}
        ):
            # A validated UI route selects a domain but must still preserve a
            # normal continuation of the same Run and a visible handoff away
            # from a different one.
            decision.mode = (
                "continue" if focus_run.agent_type == decision.target else "handoff"
            )
        run = None
        context = None
        interaction = None
        if decision.target not in {"clarify", "safety"}:
            run = self._start_or_resume(
                thread=thread, decision=decision, focus_run=focus_run
            )
            decision.context_refs = list(run.context_refs)
            envelope = self.context_builder.build(
                run_id=run.id,
                ward_id=ward_id,
                actor_id=ward_id,
                actor_role="ward",
                agent_type=run.agent_type,
                context_refs=decision.context_refs,
            )
            context = envelope.trace_snapshot()
            if run.agent_type == "planning":
                workflow = PlanningWorkflowAdapter(self.db).invoke(
                    run=run, items=planning_items, confirm=planning_confirm
                )
                run.status = workflow["status"]
                interaction = workflow["interaction"]
        self._trace(
            thread=thread,
            run=run,
            decision=decision,
            snapshot=context or {},
            duration_ms=round((perf_counter() - started) * 1000),
        )
        base_version = thread.version
        self.db.flush()
        updated = (
            self.db.query(ConversationThread)
            .filter(
                ConversationThread.id == thread.id,
                ConversationThread.version == base_version,
            )
            .update(
                {
                    ConversationThread.version: base_version + 1,
                    ConversationThread.updated_at: now(),
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            self.db.rollback()
            raise HTTPException(
                409, "conversation thread has changed; refresh before retrying"
            )
        self.db.commit()
        return CoordinatorResult(
            thread_id=thread.id,
            thread_version=base_version + 1,
            decision=decision,
            run_id=run.id if run else None,
            run_status=run.status if run else None,
            context=context,
            interaction=interaction,
        )
