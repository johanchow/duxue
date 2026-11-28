from __future__ import annotations

import hashlib
import json
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.agent_specs.definitions import load_definitions
from app.agent_specs.catalog import load_catalog
from app.agent_specs.release_runtime import configured_call
from app.application.commands.companion_history import history_is_visible, lock_history
from app.application.ports.companion import (
    CoordinatorResult,
    IntentClassifier,
    RouteDecision,
    RunInvocation,
    SceneSwitchVerifier,
    WorkflowOutcome,
)
from app.application.queries.run_transcript import current_turn_images
from app.contexts.companion.domain.intent_router import IntentRouter
from app.infrastructure.ai.intent_classifier import ModelIntentClassifier
from app.infrastructure.ai.scene_switch_verifier import ModelSceneSwitchVerifier
from app.infrastructure.observability.telemetry import (
    agent_infra_span,
    agent_step_span,
    agent_workflow_span,
    record_agent_input,
    record_agent_outcome,
    record_agent_output,
    record_agent_route,
    record_tutor_subgoal_committed,
    set_agent_context,
    set_observation_payload,
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
    Sprint,
    now,
    uid,
)
from app.infrastructure.persistence.workflow_dispatcher import (
    SqlAlchemyWorkflowDispatcher,
)

_ACTIVE_STATUSES = ("active", "waiting_for_ward", "paused")
_RESUMABLE_STATUSES = ("waiting_for_ward", "paused", "failed", "timed_out")
_CLARIFY_REPLY = "你想先聊哪个问题？可以再说具体一点。"
_SAFETY_REPLY = "如果你现在很难受，请立刻告诉身边的大人。"
_VALID_HINTS = {"tutoring"}


class CompanionCoordinator:
    """Owns only Thread/Run continuity and fenced workflow dispatch.

    Routing commits before a workflow begins.  The target workflow's result is
    then accepted only if Run, turn, attempt and Thread focus still match.
    """

    def __init__(
        self, db: Session, router: IntentRouter | None = None, dispatcher=None,
        classifier: IntentClassifier | None = None,
        switch_verifier: SceneSwitchVerifier | None = None,
    ):
        self.db = db
        self.router = router or IntentRouter()
        self.classifier = classifier or ModelIntentClassifier()
        self.switch_verifier = switch_verifier or ModelSceneSwitchVerifier()
        self.dispatcher = dispatcher or SqlAlchemyWorkflowDispatcher(db)

    @staticmethod
    def _digest(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def _thread(self, *, ward_id: str, thread_id: str | None, expected_version: int | None) -> ConversationThread:
        ward = lock_history(self.db, ward_id)
        if thread_id is None:
            if expected_version not in {None, 0}:
                raise HTTPException(409, "new thread must use version 0")
            thread = ConversationThread(ward_id=ward_id, history_generation=ward.history_generation)
            self.db.add(thread)
            self.db.flush()
            return thread
        thread = self.db.get(ConversationThread, thread_id)
        if thread is None or thread.deleted or thread.ward_id != ward_id or thread.history_generation != ward.history_generation:
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
        if decision.target == "tutoring":
            from app.agent_specs.tutoring_paths import new_run_version
            run.graph_version = new_run_version(load_catalog().spec("tutoring"), run_id)
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
        if command.thread_id and not history_is_visible(self.db, ward_id, command.thread_id):
            raise HTTPException(409, "conversation history has been cleared")
        if command.completed_at is None:
            raise HTTPException(409, "command is already in progress")
        result = CoordinatorResult.model_validate(command.result)
        if command.thread_id and result.thread_version <= self.db.get(ConversationThread, command.thread_id).clear_version:
            raise HTTPException(409, "conversation history has been cleared")
        return result

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
            return "请再说一点你想讨论的问题。"
        return None

    @staticmethod
    def _visible_interaction_ref(outcome: WorkflowOutcome) -> dict | None:
        content = CompanionCoordinator._visible_content_ref(outcome)
        refs = (outcome.next_interaction or {}).get("image_target_refs")
        if refs:
            return {**(content or {}), "image_target_refs": list(refs)}
        return content

    @staticmethod
    def _visible_content_ref(outcome: WorkflowOutcome) -> dict | None:
        payload = outcome.next_interaction or outcome.response or {}
        kind = payload.get("kind")
        if kind == "creative_focus_reminder":
            return {"kind": kind, "focus_id": payload["focus_id"]}
        if kind == "creative_work":
            return {"kind": kind, "artifact_id": payload["artifact_id"]}
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

    @trace_agent_turn
    @configured_call
    def handle(
        self, *, ward_id: str, content: str, thread_id: str | None,
        expected_thread_version: int | None, route_hint: str | None,
        command_id: str | None = None,
        study_session_id: str | None = None,
        tutoring_directive: str | None = None, tutoring_intent: str | None = None,
        attachment_keys: list[str] | None = None,
        structured_command: dict | None = None, voice_display_text: str | None = None,
    ) -> CoordinatorResult:
        started = perf_counter()
        command_id = command_id or str(uuid4())
        if tutoring_intent == "pronunciation" and route_hint is None:
            route_hint = "tutoring"
        turn = {
            "study_session_id": study_session_id, "tutoring_directive": tutoring_directive,
            "tutoring_intent": tutoring_intent,
            "content": content,
            "attachment_keys": attachment_keys or [],
            "structured_command": structured_command,
        }
        fingerprint = {"thread_id": thread_id, "expected_version": expected_thread_version, "route_hint": route_hint, "turn": turn}
        if voice_display_text:
            fingerprint["voice_display_text"] = voice_display_text
        digest = self._digest(fingerprint)
        lock_history(self.db, ward_id)
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
        if thread.version == 0 and thread.title == "新对话" and content.strip():
            thread.title = content.strip()[:40]
        set_agent_context(thread_id=thread.id)
        command = CompanionCommand(id=command_id, ward_id=ward_id, thread_id=thread.id, payload_digest=digest)
        self.db.add(command)
        visible_content = content
        focus_run = self._focus_run(thread)
        from app.agent_specs.runtime import execute_workflow, notify_node_started

        intent_schema = load_definitions().units["companion.intent"].output_schema
        study_controls = "study_control" in intent_schema["properties"]
        if study_controls and structured_command and structured_command["command"] != "sprint_command":
            raise HTTPException(410, "此交互已退场")
        judge_current_turn = (
            "teaching_policy" in intent_schema["required"]
            and not structured_command
            and (bool(content.strip()) or bool(attachment_keys))
        )

        def classify(state):
            state["proposal"] = None
            state["switch_allowed"] = None
            if study_controls and structured_command:
                return
            if not judge_current_turn and (self.router.blocks_for_safety(content) or route_hint in _VALID_HINTS):
                return
            from app.application.queries.run_transcript import load_visible_utterances
            state["recent_utterances"] = load_visible_utterances(
                self.db, ward_id=ward_id, thread_id=thread.id, exclude_turn_id=None,
            )
            state["images"] = current_turn_images(ward_id, attachment_keys)
            sprint = None
            if "off_sprint_topic" in intent_schema["properties"]:
                sprint = self.db.query(Sprint.id, Sprint.topic).filter_by(ward_id=ward_id, status="active").first()
            state["sprint_id"] = sprint.id if sprint else None
            state["proposal"] = self.classifier.propose(
                content=content, focus_agent_type=getattr(focus_run, "agent_type", None),
                recent_utterances=state["recent_utterances"], current_images=state["images"],
                **({"sprint_topic": sprint.topic} if sprint else {}),
            )

        def cross_scene(state):
            proposal = state["proposal"]
            if judge_current_turn:
                return False
            return bool(focus_run is not None and proposal is not None and proposal.intent in _VALID_HINTS
                        and proposal.intent != focus_run.agent_type)

        def verify_switch(state):
            from app.agent_specs.runtime import GateDecision
            with agent_step_span("route", "switch_confirm") as span:
                set_observation_payload(span, input={
                    "content": content, "current_agent_type": focus_run.agent_type,
                    "proposed_agent_type": state["proposal"].intent,
                })
                state["switch_allowed"] = self.switch_verifier.confirm(
                    content=content, current_agent_type=focus_run.agent_type,
                    proposed_agent_type=state["proposal"].intent,
                    recent_utterances=state["recent_utterances"], current_images=state["images"],
                )
                set_observation_payload(span, output={"allow_switch": state["switch_allowed"]})
                return GateDecision("allow" if state["switch_allowed"] is True else "deny", "scene_switch")

        def decide(state):
            proposal = state["proposal"]
            if judge_current_turn and (proposal is None or proposal.teaching_policy is None):
                proposal = None
            return self.router.decide(
                content=content, route_hint=None if judge_current_turn else route_hint,
                focus_run=focus_run, proposal=proposal,
                current_turn_policy=judge_current_turn,
                has_image=bool(attachment_keys), switch_allowed=True if judge_current_turn else state["switch_allowed"],
            )

        with agent_step_span("route", "intent_route") as route_span:
            notify_node_started("companion.route")
            set_observation_payload(route_span, input={
                "content": content, "route_hint": route_hint,
                "focus_agent_type": getattr(focus_run, "agent_type", None),
            })
            routing = execute_workflow(
                load_catalog().spec("companion"),
                handlers={"companion.intent": classify, "companion.scene-switch": verify_switch, "decide": decide},
                conditions={"cross_scene": cross_scene, "direct": lambda state: not cross_scene(state)},
            )
            decision = routing["results"]["companion.final_route"]
            proposal = routing["proposal"]
            if proposal is not None:
                route_span.set_attribute("agent.initial_intent", proposal.intent)
                if proposal.teaching_policy:
                    route_span.set_attribute("agent.teaching_policy", proposal.teaching_policy)
                route_span.set_attribute("agent.history_image_ref", proposal.history_image_ref)
                route_span.set_attribute("agent.tutoring_thinking_effort", proposal.thinking_effort)
            route_span.set_attribute("agent.proposed_target", decision.target)
            route_span.set_attribute("agent.proposed_mode", decision.mode)
            set_observation_payload(route_span, output=decision.model_dump(mode="json"))
        if decision.mode == "start" and focus_run is not None and decision.target not in {"clarify", "safety"}:
            decision.mode = "continue" if focus_run.agent_type == decision.target else "handoff"
        if structured_command:
            issued = (focus_run.outcome or {}) if focus_run else {}
            if (structured_command.get("command") != "sprint_command" or focus_run is None
                    or focus_run.agent_type != "tutoring"
                    or structured_command.get("interaction_id") != issued.get("issued_actions", {}).get("sprint_command")
                    or structured_command.get("payload") != issued.get("issued_payloads", {}).get("sprint_command")):
                raise HTTPException(409, "挑战交互已失效，请重新查看")
            decision.target, decision.mode = "tutoring", "continue"
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
            set_observation_payload(route_span, input={
                "target": decision.target, "mode": decision.mode,
                "route_reason": decision.route_reason,
            })
            route_span.set_attribute("agent.target", decision.target)
            route_span.set_attribute("agent.mode", decision.mode)
            route_span.set_attribute("agent.route_reason", decision.route_reason)
            set_observation_payload(route_span, output=decision.model_dump(mode="json"))
            record_agent_route(target=decision.target, mode=decision.mode, reason=decision.route_reason)
        with agent_infra_span("companion.pre_commit"):
            self._trace(thread=thread, run=run, decision=decision, snapshot={})
            version = self._advance_thread(thread)
            self._write_transcript(
                thread=thread, command_id=command_id, author_type="ward", content=visible_content,
                thread_version=version, run=run, turn_id=run.current_turn_id if run else None,
                attempt=run.attempt if run else None,
                attachment_refs=attachment_keys,
                interaction_ref=({"voice_display_text": voice_display_text}
                                 if voice_display_text and decision.target == "tutoring"
                                 and not structured_command and not tutoring_intent else None),
            )
            terminal_reply = { "clarify": _CLARIFY_REPLY, "safety": _SAFETY_REPLY }.get(decision.target)
            if terminal_reply is not None:
                thread.version = version
                version = self._advance_thread(thread)
                self._write_transcript(
                    thread=thread, command_id=command_id, author_type="companion",
                    content=terminal_reply, thread_version=version,
                    interaction_ref=None,
                )
            if run is None:
                result = CoordinatorResult(thread_id=thread.id, thread_version=version, decision=decision,
                                           interaction=None, command_id=command_id)
                command.result, command.completed_at = result.model_dump(), now()
                self.db.commit()
                if terminal_reply is not None:
                    record_agent_output(terminal_reply)
                record_agent_outcome(
                    agent_type=decision.target, status="closed",
                    duration_ms=round((perf_counter() - started) * 1000),
                )
                return result
            self.db.commit()
            if terminal_reply is not None:
                record_agent_output(terminal_reply)
            # The conditional SQL update deliberately bypasses the identity map;
            # reload before the outcome transaction so its fence sees the new
            # Thread version rather than the pre-routing snapshot.
            self.db.expire_all()

        if run.agent_type == "tutoring":
            turn = {**turn, "tutoring_graph_version": run.graph_version}
            if proposal is not None:
                if (
                    not attachment_keys
                    and proposal.history_image_ref == "none"
                    and turn.get("tutoring_intent") != "compare_previous_image"
                ):
                    turn["history_image_ref"] = "none"
                if proposal.teaching_policy:
                    turn["teaching_policy"] = proposal.teaching_policy
                    if proposal.teaching_policy == "pronunciation":
                        turn["tutoring_intent"] = "pronunciation"
                    elif turn.get("tutoring_intent") == "pronunciation":
                        turn.pop("tutoring_intent")
                if proposal.off_sprint_topic:
                    turn["off_topic_sprint_id"] = routing.get("sprint_id")
                turn["thinking_effort"] = proposal.thinking_effort
                if proposal.thinking_effort == "off":
                    turn["disable_thinking"] = True
        invocation = RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=ward_id, agent_type=run.agent_type,
            turn=turn, turn_id=run.current_turn_id, command_id=command_id, attempt=run.attempt,
            context_refs=decision.context_refs, resume_from_checkpoint=decision.mode == "continue",
        )
        try:
            with agent_workflow_span(agent_type=run.agent_type, run_id=run.id, thread_id=thread.id) as workflow_span:
                set_observation_payload(workflow_span, input=invocation.model_dump(mode="json"))
                notify_node_started(f"companion.{run.agent_type}")
                study_action = proposal.study_control if proposal and study_controls else None
                confirm_sprint = study_controls and (structured_command or {}).get("command") == "sprint_command"
                if run.agent_type == "tutoring" and (study_action or confirm_sprint):
                    from app.application.workflows.study_conversation import StudyConversation
                    study = StudyConversation(self.db)
                    if confirm_sprint:
                        outcome = study.confirm(run, invocation, structured_command["payload"])
                    else:
                        context = study._current_sprint_context(ward_id)
                        outcome = study.handle_action(run, invocation, study_action,
                            expected_quiet_version=context.get("camera_hints_version"))
                elif run.agent_type == "tutoring" and proposal and proposal.teaching_policy:
                    from app.application.agent.selected_skill import execute_selected_skill
                    from app.application.commands.creative_works import create_candidate
                    creative = (proposal.creative_work and proposal.teaching_policy == "standard"
                                and not structured_command and not attachment_keys)
                    if creative:
                        tool, skill = "artifact.create_or_revise", "edu.creative_studio"
                        arguments = {"artifact_type": "creative_work"}
                        def invoke():
                            return create_candidate(self.db, invocation)
                    else:
                        tool, skill = "tutoring.run_homework_turn", "edu.homework_tutoring"
                        arguments = {"content": turn["content"]}
                        def invoke():
                            return self.dispatcher.invoke(invocation)

                    def authorized(phase, result):
                        if creative and turn["teaching_policy"] != "standard":
                            return False
                        return phase == "write" or isinstance(result, WorkflowOutcome)

                    def creative_review(phase, result):
                        if phase == "write":
                            return creative
                        response = result.response or {}
                        if response.get("kind") == "creative_work":
                            from app.agent_specs.creative_work import Story
                            return Story.model_validate(response["candidate"]).title == response["content"]
                        return response.get("kind") in {"text", "creative_focus_reminder"}

                    outcome = execute_selected_skill(role="ward", owner=ward_id, thread_id=thread.id,
                        message=turn["content"], attachments=attachment_keys, skill=skill,
                        tool=tool, arguments=arguments, invoke=invoke,
                        gates={"tutoring.answer_protection":authorized, "ward.anti_ghostwriting":creative_review},
                        summarize=lambda result: str((result.response or {}).get("content") or result.run_status))
                else:
                    outcome = self.dispatcher.invoke(invocation)
                workflow_span.set_attribute("agent.run_status", outcome.run_status)
                workflow_span.set_attribute("agent.outcome_type", outcome.outcome_type or "unknown")
                set_observation_payload(workflow_span, output=outcome.model_dump(mode="json"))
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
            failure_text = "暂时无法处理这条消息，请稍后重试。"
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
        with agent_infra_span("companion.record_outcome"):
            accepted, result = self._persist_outcome(
                run_id=invocation.run_id, thread_id=invocation.thread_id, ward_id=ward_id,
                turn_id=invocation.turn_id, attempt=invocation.attempt, outcome=outcome,
                decision=decision, duration_ms=duration_ms, command_id=command_id,
                build_result=True,
            )
        if not accepted or result is None:
            raise HTTPException(409, "conversation changed before reply completed")
        record_agent_outcome(agent_type=run.agent_type, status=outcome.run_status, duration_ms=duration_ms)
        return result

    def record_outcome(self, *, run_id: str, thread_id: str, ward_id: str, turn_id: str, attempt: int,
                       outcome: WorkflowOutcome, decision: RouteDecision, duration_ms: int,
                       command_id: str | None = None) -> bool:
        accepted, _ = self._persist_outcome(
            run_id=run_id, thread_id=thread_id, ward_id=ward_id, turn_id=turn_id,
            attempt=attempt, outcome=outcome, decision=decision, duration_ms=duration_ms,
            command_id=command_id, build_result=False,
        )
        return accepted

    def _persist_outcome(self, *, run_id: str, thread_id: str, ward_id: str, turn_id: str, attempt: int,
                         outcome: WorkflowOutcome, decision: RouteDecision, duration_ms: int,
                         command_id: str | None = None,
                         build_result: bool = False) -> tuple[bool, CoordinatorResult | None]:
        ward = lock_history(self.db, ward_id)
        self.db.expire_all()
        run = self.db.get(AgentRun, run_id)
        thread = self.db.get(ConversationThread, thread_id)
        if run is None or thread is None or run.ward_id != ward_id or run.thread_id != thread.id:
            self.db.rollback()
            return False, None
        if thread.deleted or thread.history_generation != ward.history_generation or run.attempt != attempt or run.current_turn_id != turn_id or thread.focus_run_ref != run.run_ref:
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
            return False, None
        run.status = outcome.run_status
        run.graph_checkpoint_ref = outcome.checkpoint_ref
        run.context_refs = outcome.context_refs
        run.failure = outcome.failure or {}
        interaction = outcome.response or outcome.next_interaction or {}
        if interaction.get("kind") == "creative_work":
            from app.application.commands.creative_works import persist_candidate
            persist_candidate(self.db, thread, interaction)
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
            "issued_payloads": {action.get("command"): action.get("payload")
                                for action in interaction.get("actions", []) if action.get("enabled")},
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
            self._write_transcript(
                thread=thread, command_id=command_id, author_type="companion",
                content=visible_content, thread_version=version, run=run, turn_id=turn_id,
                attempt=attempt, interaction_ref=self._visible_interaction_ref(outcome),
                attachment_refs=outcome.reviewed_photo_keys,
            )
        result: CoordinatorResult | None = None
        if build_result and command_id is not None:
            result = CoordinatorResult(
                thread_id=thread.id, thread_version=version, decision=decision,
                run_id=run.id, run_status=run.status, context=outcome.context_snapshot,
                interaction=outcome.response or outcome.next_interaction, command_id=command_id,
            )
            command = self.db.get(CompanionCommand, command_id)
            if command is not None:
                command.result, command.completed_at = result.model_dump(), now()
        self.db.commit()
        record_tutor_subgoal_committed()
        if visible_content is not None and command_id is not None:
            record_agent_output(visible_content)
        self.db.expire_all()
        return True, result

    def cancel(self, *, ward_id: str, run_id: str, command_id: str, expected_thread_version: int | None = None) -> CoordinatorResult:
        digest = self._digest({"operation": "cancel", "run_id": run_id, "expected_version": expected_thread_version})
        lock_history(self.db, ward_id)
        cached = self._restore_idempotent(command_id, ward_id, digest)
        if cached is not None:
            return cached
        run = self.db.get(AgentRun, run_id)
        if run is None or run.ward_id != ward_id:
            raise HTTPException(404, "agent run not found")
        thread = self.db.get(ConversationThread, run.thread_id)
        if not history_is_visible(self.db, ward_id, thread.id):
            raise HTTPException(404, "conversation thread not found")
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
