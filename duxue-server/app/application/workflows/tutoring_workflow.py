from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.ports.tutoring import SafetyScreeningPort
from app.application.queries.context_builder import ContextBuilder
from app.application.workflows.pronunciation_guidance import (
    build_interaction,
    project_lesson,
)
from app.application.workflows.teaching_skills import history_candidates
from app.application.workflows.tutor_loop import call_tutor_model, vet_candidate
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutor_visual import describe
from app.application.workflows.tutor_turn import (
    FALLBACK_TEXT,
    REMINDER,
    SAFE_TEXT,
    LeakJudgePort,
    TutorModelPort,
    build_tutor_instruction,
)
from app.contexts.companion.domain.policy import PolicyRegistry
from app.contexts.tutoring.domain.tutor_permit import (
    PROTECTED_STATUSES,
    ProblemAssessment,
    ProblemState,
    TutorPermitPolicy,
)
from app.infrastructure.ai import components
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.observability.telemetry import record_llm_fallback, record_tutor_turn_result
from app.infrastructure.persistence.models import (
    StudySession,
    StudySessionInterval,
    Task,
    TutoringMessage,
    TutoringProblem,
    TutoringSession,
    now,
)


def _state(row: TutoringProblem | None) -> ProblemState | None:
    if row is None:
        return None
    return ProblemState(
        status=row.status, active_subgoal=row.active_subgoal,
        substantive_attempts=row.substantive_attempts, hints_given=row.hints_given,
        evidence_summary=row.evidence_summary,
    )


def _store(row: TutoringProblem, state: ProblemState) -> None:
    row.status = state.status
    row.active_subgoal = state.active_subgoal
    row.substantive_attempts = state.substantive_attempts
    row.hints_given = state.hints_given
    row.evidence_summary = state.evidence_summary


class TutoringWorkflow:
    """tutor-turn.v3：模型驱动一轮，代码守住入口许可和出口检查。"""

    def __init__(
        self, db: Session, turn_model: TutorModelPort | None = None, leak_judge: LeakJudgePort | None = None,
        safety_screening: SafetyScreeningPort | None = None,
    ):
        self.db = db
        self.turn_model = turn_model
        self.leak_judge = leak_judge
        self.safety_screening = safety_screening
        self._media_cache: dict[str, tuple[list[dict], list[str | None]]] = {}

    def _model(self) -> TutorModelPort:
        if self.turn_model is None:
            from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway
            self.turn_model = QwenTutorTurnGateway()
        return self.turn_model

    def _judge(self) -> LeakJudgePort:
        if self.leak_judge is None:
            from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge
            self.leak_judge = QwenLeakJudge()
        return self.leak_judge

    def _safety(self) -> SafetyScreeningPort:
        if self.safety_screening is None:
            from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening
            self.safety_screening = LocalSafetyScreening()
        return self.safety_screening

    def _media(self, invocation: RunInvocation) -> tuple[list[dict], list[str | None]]:
        """Window rows with their images, plus this turn's images. Read once per turn."""
        key = f"{invocation.run_id}:{invocation.turn_id}"
        if key not in self._media_cache:
            from app.application.queries.run_transcript import (
                current_turn_images,
                load_visible_utterances,
            )

            self._media_cache[key] = (
                load_visible_utterances(
                    self.db, ward_id=invocation.ward_id, thread_id=invocation.thread_id,
                    exclude_turn_id=invocation.turn_id,
                ),
                current_turn_images(invocation.ward_id, invocation.turn.get("attachment_keys")),
            )
        return self._media_cache[key]

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        return self._turn(invocation)

    def _find_session(self, ward_id: str, session_id: str | None) -> StudySession | None:
        if session_id:
            session = self.db.get(StudySession, session_id)
            if session is None:
                raise HTTPException(404, "study session not found")
            if session.ward_id != ward_id:
                raise HTTPException(403, "study session does not belong to Ward")
            return session
        return (
            self.db.query(StudySession)
            .filter(StudySession.ward_id == ward_id, StudySession.status.in_(("active", "paused")))
            .order_by(StudySession.started_at.desc())
            .first()
        )

    def _create_session(self, ward_id: str) -> StudySession:
        session = StudySession(ward_id=ward_id, task_id=None, status="active")
        self.db.add(session)
        self.db.flush()
        self.db.add(StudySessionInterval(study_session_id=session.id))
        publish_learning_fact(
            self.db, ward_id=ward_id, event_type="study_session.started",
            source_type="study_session", source_id=session.id, payload={"task_id": None},
        )
        return session

    def _ensure_tutor(self, ward_id, session, tutor, content):
        """写入前才打开会话。发音和澄清是只读的，不会走到这里。"""
        session = session or self._create_session(ward_id)
        if tutor is None:
            tutor = TutoringSession(
                ward_id=session.ward_id, study_session_id=session.id,
                question_summary=content, model_name=components.model_for("tutoring.turn"),
            )
            self.db.add(tutor)
            self.db.flush()
        return session, tutor

    def _open_problem(self, tutor: TutoringSession) -> TutoringProblem | None:
        """The latest problem whose answer is still protected: `open`, or `submitted`.

        A submission is the Ward's proposal, not permission to show the answer, so it stays
        in force until a code policy releases it (see ``tutor_permit.Disclosure``)."""
        return (
            self.db.query(TutoringProblem)
            .filter(
                TutoringProblem.tutoring_session_id == tutor.id,
                TutoringProblem.status.in_(sorted(PROTECTED_STATUSES)),
            )
            .order_by(TutoringProblem.created_at.desc())
            .first()
        )

    def _task_title(self, task_id: str | None) -> str | None:
        task = self.db.get(Task, task_id) if task_id else None
        return task.title if task is not None else None

    def _call_model(self, envelope, instruction, window, images, tools: TutorToolbox):
        """有界循环由 tutor_loop 提供（评测共用）。返回候选或 None。"""
        try:
            model = self._model()
        except Exception as error:  # noqa: BLE001 - provider failures must fall back safely.
            record_llm_fallback(operation="tutor_turn", reason=str(error))
            return None
        return call_tutor_model(model, envelope, instruction, window, images, tools).candidate

    def _turn(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn
        policy = PolicyRegistry()
        envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
            run_id=invocation.run_id, ward_id=invocation.ward_id, actor_id=invocation.ward_id,
            actor_role="ward", agent_type="tutoring", context_refs=invocation.context_refs,
            context_spec=policy.context_spec("tutoring"),
        )
        session = self._find_session(invocation.ward_id, turn.get("study_session_id"))
        tutor = (
            self.db.query(TutoringSession).filter_by(study_session_id=session.id).one_or_none()
            if session is not None else None
        )
        directive = turn.get("tutoring_directive") or "ask"
        if directive == "close":
            if tutor is None:
                raise HTTPException(409, "there is no tutoring session to close")
            if tutor.status != "closed":
                tutor.status = "closed"
                tutor.closed_at = now()
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.session_closed",
                source_type="tutoring_session", source_id=tutor.id,
                payload={"tutoring_session_id": tutor.id, "study_session_id": session.id},
            )
            return WorkflowOutcome(
                run_status="closed", outcome_type="completed", context_refs=[f"tutoring_session:{tutor.id}"],
                next_interaction={"status": "closed"}, context_snapshot=envelope.trace_snapshot(),
            )
        if tutor is not None and tutor.status == "closed":
            raise HTTPException(409, "tutoring session is closed")
        if session is not None and session.status not in {"active", "paused"}:
            raise HTTPException(409, "study session is no longer open for tutoring")

        content = turn.get("content", "")
        problem_row = self._open_problem(tutor) if tutor is not None else None
        permit = TutorPermitPolicy.permit(_state(problem_row))
        task_title = self._task_title(session.task_id if session else None)
        task_active = bool(session and session.task_id and session.status in {"active", "paused"})
        if self._safety().blocks_input(text=content):
            session, tutor = self._ensure_tutor(invocation.ward_id, session, tutor, content)
            refs = [f"tutoring_session:{tutor.id}"]
            self._ward_message(tutor, content)
            return self._reply(
                invocation, tutor, refs, envelope, text=SAFE_TEXT, blocked=True,
                permit=permit, problem_status=problem_row.status if problem_row else None,
            )
        if directive == "understood":
            session, tutor = self._ensure_tutor(invocation.ward_id, session, tutor, content)
            ward_msg = self._ward_message(tutor, content)
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.understanding_confirmed",
                source_type="tutoring_message", source_id=ward_msg.id, source="ward", visibility="ward",
                payload={"tutoring_session_id": tutor.id, "study_session_id": session.id},
            )
            return WorkflowOutcome(
                run_status="waiting_for_ward", outcome_type="waiting", context_refs=[f"tutoring_session:{tutor.id}"],
                next_interaction={"status": "understood", "problem_status": problem_row.status if problem_row else None,
                                  "answer_protected": permit.answer_protected, "safety_blocked": False},
                context_snapshot=envelope.trace_snapshot(),
            )

        from app.application.queries.run_transcript import ward_media_prefix

        prefix = ward_media_prefix(invocation.ward_id)
        if any(not str(key).startswith(prefix) for key in turn.get("attachment_keys") or []):
            interaction = build_interaction(
                invocation=invocation, kind="text", text="这次不能读取这张图片。请重新拍一张再发。",
            )
            return WorkflowOutcome(
                run_status="waiting_for_ward", outcome_type="response",
                next_interaction={**interaction, "status": "rejected", "reason": "unauthorized_media"},
            )
        window, images = self._media(invocation)
        candidates = history_candidates(window)
        instruction = build_tutor_instruction(
            content=content, permit=permit, history_candidates=candidates,
            tutoring_intent=turn.get("tutoring_intent"),
        )
        tools = TutorToolbox(
            self.db, tutoring_session_id=tutor.id if tutor else None, problem=problem_row,
            task_title=task_title, task_active=task_active, window=window,
        )
        candidate = self._call_model(envelope.model_dump(), instruction, window, images, tools)
        verdict = None
        visual = None
        failure = "no_candidate"
        vetting = None
        if candidate is not None:
            vetting = vet_candidate(
                candidate, permit=permit,
                authorized_refs=frozenset(tools.authorized_refs),
                has_work_input=bool(content.strip() or images), leak_judge=self._judge(),
                task_title=task_title, problem_summary=problem_row.summary if problem_row else content,
            )
            candidate, verdict, visual = vetting.candidate, vetting.verdict, vetting.visual
            failure = vetting.failure
        failed = candidate is None or verdict is None or not verdict.ok
        # 独立输出安全审核看孩子将看到的全部文字：正文与图里的每个字。
        safety = not failed and (
            candidate.act == "safety" or self._safety().blocks_output(
                text=candidate.content if visual is None else f"{candidate.content}\n{describe(visual)}",
            )
        )
        # 发音和澄清是只读展示：不打开会话，不写消息、事实或题目记录。
        if not failed and not safety and candidate.act == "pronounce":
            outcome = project_lesson(self.db, invocation, candidate.lesson)
            outcome.context_snapshot = envelope.trace_snapshot()
            record_tutor_turn_result(
                act=candidate.act, relation=candidate.relation, topic=candidate.topic, depth=candidate.depth, outcome="shown", reason=None,
                shown=candidate.content,
            )
            return outcome
        if not failed and not safety and candidate.act == "clarify":
            text = candidate.content
            listed = "\n".join(f"{i}. {item}" for i, item in enumerate(candidate.candidates, start=1))
            record_tutor_turn_result(
                act=candidate.act, relation=candidate.relation, topic=candidate.topic, depth=candidate.depth, outcome="shown", reason=None, shown=text,
            )
            interaction = build_interaction(
                invocation=invocation, kind="clarify", text=f"{text}\n{listed}" if listed else text,
                actions=[{"name": "reply", "label": "回复", "command": "clarify_reply", "enabled": True}],
            )
            return WorkflowOutcome(
                run_status="waiting_for_ward", outcome_type="waiting",
                next_interaction={**interaction, "status": "needs_input"},
                context_snapshot=envelope.trace_snapshot(),
            )

        session, tutor = self._ensure_tutor(invocation.ward_id, session, tutor, content)
        refs = [f"tutoring_session:{tutor.id}"]
        ward_msg = self._ward_message(tutor, content)
        if failed:
            record_tutor_turn_result(
                act=candidate.act if candidate else None, relation=candidate.relation if candidate else None,
                outcome="fallback", reason=failure or "exit_check", shown=FALLBACK_TEXT,
                shape_flags=vetting.shape_flags if vetting else None,
            )
            return self._reply(
                invocation, tutor, refs, envelope, text=FALLBACK_TEXT, blocked=False,
                permit=permit, problem_status=problem_row.status if problem_row else None,
            )
        if safety:
            record_tutor_turn_result(
                act=candidate.act, relation=candidate.relation, outcome="blocked", reason="safety", shown=SAFE_TEXT,
            )
            return self._reply(
                invocation, tutor, refs, envelope, text=SAFE_TEXT, blocked=True,
                permit=permit, problem_status=problem_row.status if problem_row else None,
            )
        text = candidate.content
        if candidate.follow_up_question and candidate.follow_up_question not in text:
            text = f"{text.rstrip()}\n{candidate.follow_up_question}"
        work = verdict.effective_work_product
        remind = task_active and not work
        if remind and REMINDER not in text:
            text = f"{text.rstrip()}\n{REMINDER}"

        problem_status = problem_row.status if problem_row else None
        answer_protected = permit.answer_protected
        hint_index = None
        if work:
            problem_status, hint_index = self._apply_problem(
                tutor, problem_row, candidate, verdict, invocation, has_work_input=bool(content.strip() or images),
                summary=content,
            )
        message = TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=text)
        self.db.add(message)
        self.db.flush()
        payload = {"tutoring_session_id": tutor.id, "study_session_id": session.id}
        if work and candidate.student_move == "attempt":
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.attempt_recorded",
                source_type="tutoring_message", source_id=ward_msg.id, source="ward", visibility="ward",
                payload={**payload, "directive": directive},
            )
        if work and hint_index is not None:
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.hint_given",
                source_type="tutoring_message", source_id=message.id, source="system",
                payload={**payload, "hint_index": hint_index},
            )
        if candidate.topic == "spontaneous_curiosity":
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.curiosity_observed",
                source_type="tutoring_message", source_id=ward_msg.id, source="ward", visibility="ward", payload=payload,
            )
        record_tutor_turn_result(
            act=candidate.act, relation=candidate.relation, topic=candidate.topic, depth=candidate.depth, outcome="shown", reason=None, shown=text,
            visual_kind=visual.kind if visual else None, visual_dropped=vetting.visual_dropped if vetting else None,
            shape_flags=vetting.shape_flags if vetting else None,
        )
        next_interaction = {
            "status": "needs_input", "content": text, "act": candidate.act,
            "hint_index": hint_index, "problem_status": problem_status,
            "answer_protected": answer_protected if problem_status is None else problem_status in PROTECTED_STATUSES, "safety_blocked": False,
            "return_to_task": remind, "model": components.model_for("tutoring.turn"), "model_fallback": False,
        }
        if visual is not None:
            # 只有通过全部检查的图才投影；kind 由 Application 决定，模型从不返回 kind。
            next_interaction.update(build_interaction(
                invocation=invocation, kind="text_visual", text=text,
                visual=visual.model_dump(exclude_none=True),
            ))
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=refs,
            next_interaction=next_interaction,
            context_snapshot=envelope.trace_snapshot(),
        )

    def _apply_problem(self, tutor, row, candidate, verdict, invocation, *, has_work_input, summary):
        """按 `TutorPermitPolicy.advance()` 推进题目记录。返回（题目状态，本轮提示序号）。

        同一个 Ward Turn 的重放不重复计数：记录已处理过本 turn 时原样返回。
        """
        new_problem = candidate.relation == "new"
        if row is not None and not new_problem and row.last_turn_id == invocation.turn_id:
            return row.status, None
        if row is None or new_problem:
            if row is not None:
                row.status = "abandoned"
            row = TutoringProblem(tutoring_session_id=tutor.id, summary=summary[:500])
            self.db.add(row)
            self.db.flush()
        assessment = ProblemAssessment(
            effective_work_product=True, student_move=candidate.student_move,
            progress=candidate.progress, same_problem=True, act=candidate.act,
            counts_as_attempt=has_work_input, subgoal_evidence=candidate.subgoal_evidence,
            next_subgoal=candidate.next_subgoal,
        )
        before = _state(row)
        new = TutorPermitPolicy.advance(before, assessment)
        _store(row, new)
        row.last_turn_id = invocation.turn_id
        return row.status, (new.hints_given if new.hints_given > before.hints_given else None)

    def _reply(self, invocation, tutor, refs, envelope, *, text, blocked, permit, problem_status):
        self.db.add(TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=text, safety_blocked=blocked))
        self.db.flush()
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=refs,
            next_interaction={
                "status": "needs_input", "content": text, "problem_status": problem_status,
                "answer_protected": permit.answer_protected,
                "safety_blocked": blocked, "return_to_task": False,
                "model": components.model_for("tutoring.turn"), "model_fallback": not blocked,
            },
            context_snapshot=envelope.trace_snapshot(),
        )

    def _ward_message(self, tutor, content):
        message = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content)
        self.db.add(message)
        self.db.flush()
        return message
