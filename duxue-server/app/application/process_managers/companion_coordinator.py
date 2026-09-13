from __future__ import annotations

import hashlib
import json
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import AgentCheckpoint, AgentRun, AgentStreamEvent, AgentTrace, CompanionCommand, ConversationThread, now, uid
from app.infrastructure.observability.telemetry import agent_workflow_span, record_agent_input, record_agent_outcome, record_agent_route
from app.application.ports.companion import CoordinatorResult, RouteDecision, RunInvocation, WorkflowOutcome
from app.contexts.companion.domain.intent_router import IntentRouter
from app.application.workflows.planning_adapter import PlanningWorkflowAdapter
from app.infrastructure.persistence.workflow_dispatcher import SqlAlchemyWorkflowDispatcher


_ACTIVE_STATUSES = ("active", "waiting_for_ward", "paused")
_RESUMABLE_STATUSES = ("waiting_for_ward", "paused", "failed", "timed_out")


class CompanionCoordinator:
    """Owns only Thread/Run continuity and fenced workflow dispatch.

    Routing commits before a workflow begins.  The target workflow's result is
    then accepted only if Run, turn, attempt and Thread focus still match.
    """

    def __init__(self, db: Session, router: IntentRouter | None = None, dispatcher=None):
        self.db = db
        self.router = router or IntentRouter()
        self.dispatcher = dispatcher or SqlAlchemyWorkflowDispatcher(db, planning_factory=PlanningWorkflowAdapter)

    @staticmethod
    def _digest(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def _thread(self, *, ward_id: str, thread_id: str | None, expected_version: int | None) -> ConversationThread:
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
            raise HTTPException(409, "conversation thread has changed; refresh before retrying")
        return thread

    def _focus_run(self, thread: ConversationThread) -> AgentRun | None:
        if not thread.focus_run_ref:
            return None
        run = self.db.query(AgentRun).filter_by(thread_id=thread.id, run_ref=thread.focus_run_ref).one_or_none()
        # Failed/timed-out focus Runs remain visible only to permit an explicit
        # Ward retry on a later Turn; closed/cancelled Runs never resume.
        return run if run and run.status in (*_ACTIVE_STATUSES, "failed", "timed_out") else None

    def _start_or_resume(self, *, thread: ConversationThread, decision: RouteDecision, focus_run: AgentRun | None) -> AgentRun:
        if decision.mode == "continue" and focus_run is not None:
            if focus_run.status not in _RESUMABLE_STATUSES:
                raise HTTPException(409, "focus run cannot be resumed")
            if focus_run.status in {"failed", "timed_out"}:
                focus_run.attempt += 1
            focus_run.status = "active"
            focus_run.last_active_at = now()
            return focus_run
        if focus_run is not None and focus_run.status in _ACTIVE_STATUSES:
            focus_run.status = "paused"
        run_id = uid()
        run = AgentRun(
            id=run_id, thread_id=thread.id, ward_id=thread.ward_id,
            agent_type=decision.target, run_ref=f"agent_run:{run_id}", attempt=1,
        )
        self.db.add(run)
        self.db.flush()
        thread.focus_run_ref = run.run_ref
        return run

    def _trace(self, *, thread: ConversationThread, run: AgentRun | None, decision: RouteDecision, snapshot: dict, outcome: dict | None = None, duration_ms: int | None = None) -> None:
        self.db.add(AgentTrace(
            thread_id=thread.id, run_id=run.id if run else None,
            route_target=decision.target, route_mode=decision.mode, route_reason=decision.route_reason,
            context_refs=decision.context_refs, context_snapshot=snapshot,
            outcome=outcome or {"run_status": run.status if run else None},
            policy_version=run.policy_version if run else None, duration_ms=duration_ms,
        ))

    def _advance_thread(self, thread: ConversationThread) -> int:
        base_version = thread.version
        updated = self.db.query(ConversationThread).filter(
            ConversationThread.id == thread.id, ConversationThread.version == base_version,
        ).update({ConversationThread.version: base_version + 1, ConversationThread.updated_at: now()}, synchronize_session=False)
        if updated != 1:
            raise HTTPException(409, "conversation thread has changed; refresh before retrying")
        return base_version + 1

    def _restore_idempotent(self, command_id: str, ward_id: str, digest: str) -> CoordinatorResult | None:
        command = self.db.get(CompanionCommand, command_id)
        if command is None:
            return None
        if command.ward_id != ward_id or command.payload_digest != digest:
            raise HTTPException(409, "command_id was already used with a different payload")
        if command.completed_at is None:
            raise HTTPException(409, "command is already in progress")
        return CoordinatorResult.model_validate(command.result)

    def _write_stream_event(self, run: AgentRun, outcome: WorkflowOutcome) -> None:
        payload = outcome.response or outcome.next_interaction or {}
        if not payload:
            return
        sequence = self.db.query(AgentStreamEvent).filter_by(run_id=run.id, attempt=run.attempt).count() + 1
        self.db.add(AgentStreamEvent(
            run_id=run.id, attempt=run.attempt, sequence=sequence,
            event_type=outcome.outcome_type or "outcome", payload=payload,
            policy_version=run.policy_version,
        ))

    def handle(
        self, *, ward_id: str, content: str, thread_id: str | None,
        expected_thread_version: int | None, route_hint: str | None,
        command_id: str | None = None, planning_items: list[dict] | None = None,
        planning_confirm: bool = False, study_session_id: str | None = None,
        tutoring_directive: str | None = None, review_date=None,
        review_feeling: str | None = None, review_reflection: str | None = None,
        adopt_focus_kit: bool = False,
    ) -> CoordinatorResult:
        started = perf_counter()
        command_id = command_id or str(uuid4())
        turn = {
            "planning_items": planning_items, "planning_confirm": planning_confirm,
            "study_session_id": study_session_id, "tutoring_directive": tutoring_directive,
            "content": content, "review_date": review_date.isoformat() if review_date else None,
            "review_feeling": review_feeling, "review_reflection": review_reflection,
            "adopt_focus_kit": adopt_focus_kit,
        }
        digest = self._digest({"thread_id": thread_id, "expected_version": expected_thread_version, "route_hint": route_hint, "turn": turn})
        cached = self._restore_idempotent(command_id, ward_id, digest)
        if cached is not None:
            return cached

        # Phase 1: persist the routing decision before invoking any target work.
        thread = self._thread(ward_id=ward_id, thread_id=thread_id, expected_version=expected_thread_version)
        command = CompanionCommand(id=command_id, ward_id=ward_id, thread_id=thread.id, payload_digest=digest)
        self.db.add(command)
        focus_run = self._focus_run(thread)
        decision = self.router.decide(content=content, route_hint=route_hint, focus_run=focus_run)
        if decision.mode == "start" and focus_run is not None and decision.target not in {"clarify", "safety"}:
            decision.mode = "continue" if focus_run.agent_type == decision.target else "handoff"
        run = None
        if decision.target not in {"clarify", "safety"}:
            run = self._start_or_resume(thread=thread, decision=decision, focus_run=focus_run)
            decision.context_refs = list(run.context_refs)
            run.current_turn_id = str(uuid4())
        record_agent_input(
            agent_type=decision.target, run_id=run.id if run else None,
            thread_id=thread.id, content=content,
        )
        record_agent_route(target=decision.target, mode=decision.mode, reason=decision.route_reason)
        self._trace(thread=thread, run=run, decision=decision, snapshot={})
        version = self._advance_thread(thread)
        self.db.commit()
        # The conditional SQL update deliberately bypasses the identity map;
        # reload before the outcome transaction so its fence sees the new
        # Thread version rather than the pre-routing snapshot.
        self.db.expire_all()

        if run is None:
            result = CoordinatorResult(thread_id=thread.id, thread_version=version, decision=decision, command_id=command_id)
            command = self.db.get(CompanionCommand, command_id)
            command.result, command.completed_at = result.model_dump(), now()
            self.db.commit()
            record_agent_outcome(
                agent_type=decision.target, status="closed",
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return result

        invocation = RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=ward_id, agent_type=run.agent_type,
            turn=turn, turn_id=run.current_turn_id, command_id=command_id, attempt=run.attempt,
            context_refs=decision.context_refs, resume_from_checkpoint=decision.mode == "continue",
        )
        try:
            with agent_workflow_span(agent_type=run.agent_type, run_id=run.id, thread_id=thread.id):
                outcome = self.dispatcher.invoke(invocation)
        except Exception as exc:
            self.db.rollback()
            outcome = WorkflowOutcome(
                run_status="failed", outcome_type="failure",
                failure={"code": "workflow_exception", "source": "transport", "detail": str(exc)[:200], "retriable": False},
                resume_action="restart",
            )
        duration_ms = round((perf_counter() - started) * 1000)
        self.record_outcome(
            run_id=invocation.run_id, thread_id=invocation.thread_id, ward_id=ward_id,
            turn_id=invocation.turn_id, attempt=invocation.attempt, outcome=outcome,
            decision=decision, duration_ms=duration_ms,
        )
        record_agent_outcome(agent_type=run.agent_type, status=outcome.run_status, duration_ms=duration_ms)
        run = self.db.get(AgentRun, invocation.run_id)
        thread = self.db.get(ConversationThread, invocation.thread_id)
        result = CoordinatorResult(
            thread_id=thread.id, thread_version=thread.version, decision=decision,
            run_id=run.id, run_status=run.status, context=outcome.context_snapshot,
            interaction=outcome.response or outcome.next_interaction, command_id=command_id,
        )
        command = self.db.get(CompanionCommand, command_id)
        command.result, command.completed_at = result.model_dump(), now()
        self.db.commit()
        return result

    def record_outcome(self, *, run_id: str, thread_id: str, ward_id: str, turn_id: str, attempt: int, outcome: WorkflowOutcome, decision: RouteDecision, duration_ms: int) -> bool:
        run = self.db.get(AgentRun, run_id)
        thread = self.db.get(ConversationThread, thread_id)
        if run is None or thread is None or run.ward_id != ward_id or run.thread_id != thread.id:
            self.db.rollback()
            return False
        if run.attempt != attempt or run.current_turn_id != turn_id or thread.focus_run_ref != run.run_ref:
            self.db.rollback()
            current_thread = self.db.get(ConversationThread, thread_id)
            current_run = self.db.get(AgentRun, run_id)
            if current_thread is not None:
                self._trace(
                    thread=current_thread, run=current_run, decision=decision, snapshot={},
                    outcome={"late_outcome_discarded": True, "attempt": attempt, "turn_id": turn_id},
                    duration_ms=duration_ms,
                )
                self.db.commit()
            return False
        run.status = outcome.run_status
        run.graph_checkpoint_ref = outcome.checkpoint_ref
        run.context_refs = outcome.context_refs
        run.failure = outcome.failure or {}
        run.outcome = {"type": outcome.outcome_type, "resume_action": outcome.resume_action}
        if outcome.run_status == "cancelled":
            run.cancelled_at = now()
        if outcome.checkpoint_ref:
            # Keep a durable, versioned pointer to resumable graph state.  The
            # checkpointer remains the source of the state itself; this table
            # lets deletion, audit and retry reason about that pointer without
            # storing prompts or model reasoning in the application database.
            checkpoint = self.db.query(AgentCheckpoint).filter(
                AgentCheckpoint.run_id == run.id,
                AgentCheckpoint.checkpoint_ref == outcome.checkpoint_ref,
            ).one_or_none()
            if checkpoint is None:
                checkpoint = AgentCheckpoint(
                    run_id=run.id,
                    checkpoint_ref=outcome.checkpoint_ref,
                    graph_version=run.graph_version,
                    state_digest=self._digest({
                        "run_status": outcome.run_status,
                        "outcome_type": outcome.outcome_type,
                        "resume_action": outcome.resume_action,
                        "context_refs": outcome.context_refs,
                    }),
                )
                self.db.add(checkpoint)
        self._write_stream_event(run, outcome)
        self._trace(
            thread=thread, run=run, decision=decision, snapshot=outcome.context_snapshot or {},
            outcome={"run_status": outcome.run_status, "failure": outcome.failure or {}}, duration_ms=duration_ms,
        )
        self._advance_thread(thread)
        self.db.commit()
        self.db.expire_all()
        return True

    def cancel(self, *, ward_id: str, run_id: str, command_id: str, expected_thread_version: int | None = None) -> CoordinatorResult:
        digest = self._digest({"operation": "cancel", "run_id": run_id, "expected_version": expected_thread_version})
        cached = self._restore_idempotent(command_id, ward_id, digest)
        if cached is not None:
            return cached
        run = self.db.get(AgentRun, run_id)
        if run is None or run.ward_id != ward_id:
            raise HTTPException(404, "agent run not found")
        thread = self.db.get(ConversationThread, run.thread_id)
        if expected_thread_version is not None and thread.version != expected_thread_version:
            raise HTTPException(409, "conversation thread has changed; refresh before retrying")
        if run.status not in _ACTIVE_STATUSES:
            raise HTTPException(409, "agent run cannot be cancelled")
        command = CompanionCommand(id=command_id, ward_id=ward_id, thread_id=thread.id, payload_digest=digest)
        self.db.add(command)
        run.status, run.cancelled_at = "cancelled", now()
        if thread.focus_run_ref == run.run_ref:
            thread.focus_run_ref = None
        version = self._advance_thread(thread)
        result = CoordinatorResult(
            thread_id=thread.id, thread_version=version,
            decision=RouteDecision(target=run.agent_type, mode="continue", confidence=1, route_reason="ward_cancelled"),
            run_id=run.id, run_status="cancelled", command_id=command_id,
        )
        command.result, command.completed_at = result.model_dump(), now()
        self.db.commit()
        return result
