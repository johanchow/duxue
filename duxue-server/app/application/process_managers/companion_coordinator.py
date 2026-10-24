from __future__ import annotations

import hashlib
import json
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.application.ports.companion import (
    CoordinatorResult,
    IntentClassifier,
    RouteDecision,
    RunInvocation,
    WorkflowOutcome,
)
from app.application.queries.run_transcript import current_turn_images
from app.application.workflows.planning_adapter import PlanningWorkflowAdapter
from app.contexts.companion.domain.intent_router import IntentRouter
from app.infrastructure.ai.intent_classifier import ModelIntentClassifier
from app.infrastructure.observability.telemetry import (
    agent_step_span,
    agent_workflow_span,
    record_agent_input,
    record_agent_outcome,
    record_agent_output,
    record_agent_route,
    set_agent_context,
    trace_agent_turn,
)
from app.infrastructure.persistence.models import (
    AgentCheckpoint,
    AgentRun,
    AgentStreamEvent,
    AgentTrace,
    CompanionCommand,
    CompanionMessage,
    ConversationThread,
    PlanDraft,
    now,
    uid,
)
from app.infrastructure.persistence.workflow_dispatcher import (
    SqlAlchemyWorkflowDispatcher,
)

_ACTIVE_STATUSES = ("active", "waiting_for_ward", "paused")
_RESUMABLE_STATUSES = ("waiting_for_ward", "paused", "failed", "timed_out")
_CLARIFY_REPLY = (
    "我还没确定你想做哪件事，请选择：**管理任务**、**总结思考**，还是**提问探讨**？"
)
_SAFETY_REPLY = "如果你现在很难受，请立刻告诉身边的大人。"
_VALID_HINTS = {"planning", "tutoring", "reflection"}
_INTENT_CHOICES = (("planning", "管理任务"), ("reflection", "总结思考"), ("tutoring", "提问探讨"))


class CompanionCoordinator:
    """Owns only Thread/Run continuity and fenced workflow dispatch.

    Routing commits before a workflow begins.  The target workflow's result is
    then accepted only if Run, turn, attempt and Thread focus still match.
    """

    def __init__(
        self, db: Session, router: IntentRouter | None = None, dispatcher=None,
        classifier: IntentClassifier | None = None,
    ):
        self.db = db
        self.router = router or IntentRouter()
        self.classifier = classifier or ModelIntentClassifier()
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

    def _write_transcript(self, *, thread: ConversationThread, command_id: str, author_type: str,
                          content: str, thread_version: int, run: AgentRun | None = None,
                          turn_id: str | None = None, attempt: int | None = None,
                          attachment_refs: list[str] | None = None,
                          interaction_ref: dict | None = None) -> None:
        self.db.add(CompanionMessage(
            ward_id=thread.ward_id, thread_id=thread.id, command_id=command_id,
            run_id=run.id if run else None, turn_id=turn_id, attempt=attempt,
            thread_version=thread_version, author_type=author_type, content=content,
            attachment_refs=attachment_refs or [],
            interaction_ref=interaction_ref,
        ))

    @staticmethod
    def _visible_outcome_content(outcome: WorkflowOutcome) -> str | None:
        payload = outcome.response or outcome.next_interaction or {}
        for key in ("content", "assistant_text", "model_guidance", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if payload.get("status") == "needs_input":
            return "我还需要一点信息，才能继续帮你安排。"
        if payload.get("status") == "confirmed":
            return "计划已经确认好了。"
        return None

    @staticmethod
    def _visible_interaction_ref(outcome: WorkflowOutcome) -> dict | None:
        payload = outcome.next_interaction or outcome.response or {}
        kind = payload.get("kind")
        if kind == "text_visual":
            for part in payload.get("parts") or []:
                if isinstance(part, dict) and part.get("type") == "visual" and isinstance(part.get("visual"), dict):
                    return {"kind": "text_visual", "parts": [{"type": "visual", "visual": part["visual"]}]}
            return None
        if kind == "pronunciation_lesson":
            lessons = payload.get("lessons")
            if isinstance(lessons, list) and lessons and all(isinstance(item, dict) for item in lessons):
                return {"kind": "pronunciation_lesson", "lessons": lessons}
        return None

    @staticmethod
    def _intent_choice_interaction(thread_id: str, command_id: str) -> dict:
        interaction_id = f"intent:{thread_id}:{command_id}"
        return {
            "protocol": "companion-interaction.v1", "kind": "intent_choice",
            "content": _CLARIFY_REPLY, "parts": [{"type": "text", "text": _CLARIFY_REPLY}],
            "source_command_id": command_id,
            "actions": [
                {"id": interaction_id, "name": "select", "label": label,
                 "command": "choose_intent", "enabled": True, "payload": {"intent": intent}}
                for intent, label in _INTENT_CHOICES
            ],
        }

    @trace_agent_turn
    def handle(
        self, *, ward_id: str, content: str, thread_id: str | None,
        expected_thread_version: int | None, route_hint: str | None,
        command_id: str | None = None, planning_items: list[dict] | None = None,
        planning_confirm: bool = False, study_session_id: str | None = None,
        tutoring_directive: str | None = None, tutoring_intent: str | None = None, review_date=None,
        review_feeling: str | None = None, review_reflection: str | None = None,
        attachment_keys: list[str] | None = None,
        structured_command: dict | None = None,
    ) -> CoordinatorResult:
        started = perf_counter()
        command_id = command_id or str(uuid4())
        if tutoring_intent == "pronunciation" and route_hint is None:
            route_hint = "tutoring"
        turn = {
            "planning_items": planning_items, "planning_confirm": planning_confirm,
            "study_session_id": study_session_id, "tutoring_directive": tutoring_directive,
            "tutoring_intent": tutoring_intent,
            "content": content, "review_date": review_date.isoformat() if review_date else None,
            "review_feeling": review_feeling, "review_reflection": review_reflection,
            "attachment_keys": attachment_keys or [],
            "structured_command": structured_command,
        }
        digest = self._digest({"thread_id": thread_id, "expected_version": expected_thread_version, "route_hint": route_hint, "turn": turn})
        cached = self._restore_idempotent(command_id, ward_id, digest)
        if cached is not None:
            set_agent_context(thread_id=cached.thread_id)
            record_agent_input(agent_type=cached.decision.target, run_id=cached.run_id,
                               thread_id=cached.thread_id, content=content)
            if cached.interaction and isinstance(cached.interaction.get("content"), str):
                record_agent_output(cached.interaction["content"])
            return cached

        # Phase 1: persist the routing decision before invoking any target work.
        thread = self._thread(ward_id=ward_id, thread_id=thread_id, expected_version=expected_thread_version)
        set_agent_context(thread_id=thread.id)
        command = CompanionCommand(id=command_id, ward_id=ward_id, thread_id=thread.id, payload_digest=digest)
        self.db.add(command)
        visible_content = content
        choice_selected = structured_command is not None and structured_command.get("command") == "choose_intent"
        if choice_selected:
            if (planning_items is not None or planning_confirm or study_session_id is not None
                    or tutoring_directive is not None or tutoring_intent is not None
                    or review_date is not None or review_feeling is not None
                    or review_reflection is not None):
                raise HTTPException(409, "意图选择不能同时提交其他操作")
            interaction_id = structured_command.get("interaction_id")
            payload = structured_command.get("payload") or {}
            latest = (self.db.query(CompanionMessage)
                      .filter_by(ward_id=ward_id, thread_id=thread.id, author_type="companion")
                      .order_by(CompanionMessage.thread_version.desc()).first())
            issued = latest.interaction_ref if latest is not None else None
            actions = issued.get("actions", []) if isinstance(issued, dict) else []
            matching = [action for action in actions
                        if action.get("id") == interaction_id and action.get("command") == "choose_intent"
                        and action.get("enabled") is True and action.get("payload") == payload]
            if (route_hint is not None or attachment_keys or latest is None or not isinstance(issued, dict)
                    or latest.thread_version != thread.version
                    or issued.get("kind") != "intent_choice" or len(matching) != 1):
                raise HTTPException(409, "意图选择已过期，请重新说明")
            source = (self.db.query(CompanionMessage)
                      .filter_by(ward_id=ward_id, thread_id=thread.id,
                                 command_id=issued.get("source_command_id"), author_type="ward")
                      .one_or_none())
            if source is None or source.thread_version != latest.thread_version - 1:
                raise HTTPException(409, "意图选择已过期，请重新说明")
            route_hint = payload["intent"]
            content = source.content
            attachment_keys = list(source.attachment_refs or [])
            turn["content"], turn["attachment_keys"] = content, attachment_keys
            turn["structured_command"] = None
            visible_content = f"选择：{matching[0]['label']}"
        focus_run = self._focus_run(thread)
        proposal = None
        with agent_step_span("route", "intent_route") as route_span:
            if not self.router.blocks_for_safety(content) and route_hint not in _VALID_HINTS:
                from app.application.queries.run_transcript import (
                    load_visible_utterances,
                )

                proposal = self.classifier.propose(
                    content=content, focus_agent_type=getattr(focus_run, "agent_type", None),
                    recent_utterances=load_visible_utterances(
                        self.db, ward_id=ward_id, thread_id=thread.id, exclude_turn_id=None,
                    ),
                    current_images=current_turn_images(ward_id, attachment_keys),
                )
            decision = self.router.decide(
                content=content, route_hint=route_hint, focus_run=focus_run, proposal=proposal,
                has_image=bool(attachment_keys),
            )
            route_span.set_attribute("agent.proposed_target", decision.target)
            route_span.set_attribute("agent.proposed_mode", decision.mode)
        if decision.mode == "start" and focus_run is not None and decision.target not in {"clarify", "safety"}:
            decision.mode = "continue" if focus_run.agent_type == decision.target else "handoff"
        if structured_command and not choice_selected:
            # A form reply is often intentionally content-less.  Its signed
            # interaction, rather than lexical routing, selects Planning.
            if focus_run is not None and focus_run.agent_type == "planning":
                decision.target, decision.mode = "planning", "continue"
            if decision.target != "planning" or structured_command.get("command") not in {"confirm_plan", "clarify_reply", "accept_plan_suggestion"}:
                raise HTTPException(409, "当前交互不允许这个动作")
            if focus_run is None or focus_run.agent_type != "planning":
                raise HTTPException(409, "计划交互已失效，请重新审阅")
            payload = structured_command.get("payload") or {}
            draft = self.db.get(PlanDraft, payload.get("draft_id"))
            expected = payload.get("expected_draft_version")
            command_name = structured_command["command"]
            if command_name in {"confirm_plan", "accept_plan_suggestion"}:
                interaction_id = f"plan:{focus_run.id}:{focus_run.attempt}:{payload.get('draft_id')}:{expected}"
                version_valid = draft is not None and draft.version == expected
            else:
                interaction_id = f"clarify:{focus_run.id}:{focus_run.attempt}:{payload.get('draft_id')}:{draft.version if draft else None}"
                version_valid = draft is not None
            if (draft is None or draft.ward_id != ward_id or draft.status != "active"
                    or not version_valid or structured_command.get("interaction_id") != interaction_id
                    or (focus_run.outcome or {}).get("issued_actions", {}).get(
                        command_name,
                        (focus_run.outcome or {}).get("interaction_id")
                        if command_name != "accept_plan_suggestion" else None,
                    ) != interaction_id):
                raise HTTPException(409, "计划交互已过期，请重新审阅")
            if (command_name == "accept_plan_suggestion"
                    and command_name not in (focus_run.outcome or {}).get("allowed_commands", [])):
                raise HTTPException(409, "当前交互不允许采纳建议")
        run = None
        if decision.target not in {"clarify", "safety"}:
            run = self._start_or_resume(thread=thread, decision=decision, focus_run=focus_run)
            set_agent_context(run_id=run.id)
            decision.context_refs = list(run.context_refs)
            run.current_turn_id = str(uuid4())
        record_agent_input(
            agent_type=decision.target, run_id=run.id if run else None,
            thread_id=thread.id, content=visible_content,
            images=current_turn_images(ward_id, attachment_keys) if attachment_keys else None,
        )
        with agent_step_span("route", "final_route") as route_span:
            route_span.set_attribute("agent.target", decision.target)
            route_span.set_attribute("agent.mode", decision.mode)
            route_span.set_attribute("agent.route_reason", decision.route_reason)
            record_agent_route(target=decision.target, mode=decision.mode, reason=decision.route_reason)
        self._trace(thread=thread, run=run, decision=decision, snapshot={})
        version = self._advance_thread(thread)
        self._write_transcript(
            thread=thread, command_id=command_id, author_type="ward", content=visible_content,
            thread_version=version, run=run, turn_id=run.current_turn_id if run else None,
            attempt=run.attempt if run else None,
            attachment_refs=[] if choice_selected else attachment_keys,
        )
        terminal_reply = { "clarify": _CLARIFY_REPLY, "safety": _SAFETY_REPLY }.get(decision.target)
        intent_choice = (self._intent_choice_interaction(thread.id, command_id)
                         if decision.target == "clarify" else None)
        if terminal_reply is not None:
            record_agent_output(terminal_reply)
            thread.version = version
            version = self._advance_thread(thread)
            self._write_transcript(
                thread=thread, command_id=command_id, author_type="companion",
                content=terminal_reply, thread_version=version,
                interaction_ref=intent_choice,
            )
        self.db.commit()
        # The conditional SQL update deliberately bypasses the identity map;
        # reload before the outcome transaction so its fence sees the new
        # Thread version rather than the pre-routing snapshot.
        self.db.expire_all()

        if run is None:
            result = CoordinatorResult(thread_id=thread.id, thread_version=version, decision=decision,
                                       interaction=intent_choice, command_id=command_id)
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
            with agent_workflow_span(agent_type=run.agent_type, run_id=run.id, thread_id=thread.id) as workflow_span:
                outcome = self.dispatcher.invoke(invocation)
                workflow_span.set_attribute("agent.run_status", outcome.run_status)
                workflow_span.set_attribute("agent.outcome_type", outcome.outcome_type or "unknown")
        except StaleDataError as exc:
            self.db.rollback()
            raise HTTPException(409, "计划或任务已变化，请重新审阅") from exc
        except HTTPException:
            # Domain conflicts (notably a stale draft/schedule version) are
            # meaningful client outcomes.  Do not turn them into a fake 200
            # workflow failure: the API/App recovery path must receive 409.
            self.db.rollback()
            raise
        except Exception as exc:  # noqa: BLE001 - unexpected workflow failures need a visible fallback
            self.db.rollback()
            failure_text = (
                "计划整理暂不可用，请稍后重试。"
                if run.agent_type == "planning"
                else "暂时无法处理这条消息，请稍后重试。"
            )
            outcome = WorkflowOutcome(
                run_status="failed", outcome_type="failure",
                response={
                    "protocol": "companion-interaction.v1",
                    "kind": "error",
                    "content": failure_text,
                    "parts": [{"type": "text", "text": failure_text}],
                    "actions": [],
                },
                failure={"code": "workflow_exception", "source": "transport", "detail": str(exc)[:200], "retriable": False},
                resume_action="restart",
            )
        duration_ms = round((perf_counter() - started) * 1000)
        self.record_outcome(
            run_id=invocation.run_id, thread_id=invocation.thread_id, ward_id=ward_id,
            turn_id=invocation.turn_id, attempt=invocation.attempt, outcome=outcome,
            decision=decision, duration_ms=duration_ms, command_id=command_id,
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

    def record_outcome(self, *, run_id: str, thread_id: str, ward_id: str, turn_id: str, attempt: int,
                       outcome: WorkflowOutcome, decision: RouteDecision, duration_ms: int,
                       command_id: str | None = None) -> bool:
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
        interaction = outcome.response or outcome.next_interaction or {}
        run.outcome = {
            "type": outcome.outcome_type,
            "resume_action": outcome.resume_action,
            # The issued action is persisted with its run outcome.  A later
            # StructuredWardCommand must match it; clients cannot manufacture
            # a command only from a draft id and thread version.
            "interaction_id": next((action.get("id") for action in interaction.get("actions", [])
                                    if action.get("enabled")), None),
            "allowed_commands": [action.get("command") for action in interaction.get("actions", [])
                                 if action.get("enabled")],
            "issued_actions": {action.get("command"): action.get("id")
                               for action in interaction.get("actions", [])
                               if action.get("enabled") and action.get("id")},
        }
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
        version = self._advance_thread(thread)
        visible_content = self._visible_outcome_content(outcome)
        if visible_content is not None and command_id is not None:
            record_agent_output(visible_content)
            self._write_transcript(
                thread=thread, command_id=command_id, author_type="companion",
                content=visible_content, thread_version=version, run=run, turn_id=turn_id,
                attempt=attempt, interaction_ref=self._visible_interaction_ref(outcome),
            )
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
