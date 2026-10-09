from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.queries.context_builder import ContextBuilder
from app.application.workflows.pronunciation_guidance import build_interaction, project_lesson
from app.application.workflows.teaching_skills import history_candidates
from app.application.workflows.tutor_turn import (
    FALLBACK_TEXT, REMINDER, SAFE_TEXT, LeakJudgePort, TutorModelPort, TutorTurnCandidate,
    check_authority, format_schema_error,
)
from app.bootstrap.settings import settings
from app.contexts.companion.domain.policy import PolicyRegistry
from app.contexts.study.domain.tutor_permit import (
    HINT_ACTS, ProblemAssessment, ProblemState, TutorPermitPolicy,
)
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.observability.telemetry import record_llm_fallback
from app.infrastructure.persistence.models import (
    StudySession, StudySessionInterval, Task, TutoringMessage, TutoringProblem, TutoringSession, now,
)
from pydantic import ValidationError

from app.application.workflows.tutor_tools import MAX_MODEL_CALLS, MAX_TOOL_CALLS, TutorToolbox



def _state(row: TutoringProblem | None) -> ProblemState | None:
    if row is None:
        return None
    return ProblemState(
        solution_state=row.solution_state, substantive_attempts=row.substantive_attempts,
        no_progress_streak=row.no_progress_streak, hints_given=row.hints_given,
        answer_requested=row.answer_requested, status=row.status,
    )


def _store(row: TutoringProblem, state: ProblemState) -> None:
    row.solution_state = state.solution_state
    row.status = state.status
    row.substantive_attempts = state.substantive_attempts
    row.no_progress_streak = state.no_progress_streak
    row.hints_given = state.hints_given
    row.answer_requested = state.answer_requested


class TutoringWorkflow:
    """tutor-turn.v1：模型驱动一轮，代码守住入口许可和出口检查。"""

    def __init__(
        self, db: Session, turn_model: TutorModelPort | None = None, leak_judge: LeakJudgePort | None = None,
    ):
        self.db = db
        self.turn_model = turn_model
        self.leak_judge = leak_judge
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

    def _media(self, invocation: RunInvocation) -> tuple[list[dict], list[str | None]]:
        """Window rows with their images, plus this turn's images. Read once per turn."""
        key = f"{invocation.run_id}:{invocation.turn_id}"
        if key not in self._media_cache:
            from app.application.queries.run_transcript import current_turn_images, load_visible_utterances

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
                question_summary=content, model_name=settings.agent_model("tutoring"),
            )
            self.db.add(tutor)
            self.db.flush()
        return session, tutor

    def _open_problem(self, tutor: TutoringSession) -> TutoringProblem | None:
        return (
            self.db.query(TutoringProblem)
            .filter_by(tutoring_session_id=tutor.id, status="open")
            .order_by(TutoringProblem.created_at.desc())
            .first()
        )

    def _task_title(self, task_id: str | None) -> str | None:
        task = self.db.get(Task, task_id) if task_id else None
        return task.title if task is not None else None

    def _call_model(self, envelope, instruction, window, images, tools: TutorToolbox):
        """有界循环：模型要工具就执行，直到返回候选。

        至多 MAX_TOOL_CALLS 次工具、MAX_MODEL_CALLS 次主调用（含结构重试）。
        返回候选或 None。
        """
        repair: str | None = None
        observations: list[dict] = []
        tool_calls = 0
        for _ in range(MAX_MODEL_CALLS):
            try:
                raw = self._model().complete(
                    envelope=envelope, instruction=instruction, recent_utterances=window,
                    current_images=images, repair_error=repair, observations=observations,
                )
            except Exception as error:
                record_llm_fallback(operation="tutor_turn", reason=str(error))
                return None
            if isinstance(raw, dict) and "tool" in raw:
                name = str(raw.get("tool"))
                if tool_calls >= MAX_TOOL_CALLS:
                    observations.append({"tool": name, "status": "budget_exhausted"})
                else:
                    tool_calls += 1
                    observations.append(tools.run(name, raw.get("args")))
                continue
            try:
                return TutorTurnCandidate.model_validate(raw)
            except (ValidationError, ValueError) as error:
                if repair is not None:  # 结构错误只重试一次
                    break
                repair = format_schema_error(error)
        record_llm_fallback(operation="tutor_turn", reason="invalid_model_candidate")
        return None

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

        content = turn.get("content", "")
        problem_row = self._open_problem(tutor) if tutor is not None else None
        permit = TutorPermitPolicy.permit(
            _state(problem_row), task_id=session.task_id if session else None,
            session_status=session.status if session else "",
            task_title=self._task_title(session.task_id if session else None),
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
                next_interaction={"status": "understood", "solution_state": permit.solution, "safety_blocked": False},
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
        instruction = json.dumps({
            "student_said": content,
            "permit": permit.as_context(),
            "history_candidates": candidates,
            "expected_act": "pronounce" if turn.get("tutoring_intent") == "pronunciation" else None,
        }, ensure_ascii=False)
        tools = TutorToolbox(
            self.db, tutoring_session_id=tutor.id if tutor else None, problem=problem_row,
            task_title=permit.task_title, task_active=permit.must_remind_task, window=window,
        )
        candidate = self._call_model(envelope.model_dump(), instruction, window, images, tools)
        verdict = None
        if candidate is not None:
            verdict = check_authority(
                candidate, permit, has_open_problem=problem_row is not None,
                authorized_history_refs=frozenset(tools.authorized_refs),
                has_work_input=bool(content.strip() or images),
            )
            if not verdict.ok:
                record_llm_fallback(operation="tutor_turn", reason=verdict.reason)
            elif verdict.needs_leak_check:
                judged = self._judge().leaks(
                    text=f"{candidate.content}\n{candidate.follow_up_question or ''}",
                    task_title=permit.task_title, problem_summary=problem_row.summary if problem_row else content,
                )
                if judged is not False:  # True 泄露；None 判定失败，同样 fail-closed
                    verdict = None
                    record_llm_fallback(operation="tutor_turn", reason="leak_check_failed" if judged is None else "leak_detected")
        failed = candidate is None or verdict is None or not verdict.ok
        safety = not failed and candidate.question_kind == "safety"
        # 发音和澄清是只读展示：不打开会话，不写消息、事实或题目记录。
        if not failed and not safety and candidate.act == "pronounce":
            outcome = project_lesson(self.db, invocation, candidate.lesson)
            outcome.context_snapshot = envelope.trace_snapshot()
            return outcome
        if not failed and not safety and candidate.act == "clarify":
            text = candidate.content
            listed = "\n".join(f"{i}. {item}" for i, item in enumerate(candidate.candidates, start=1))
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
            return self._reply(invocation, tutor, refs, envelope, text=FALLBACK_TEXT, blocked=False, permit_solution=permit.solution)
        if safety:
            return self._reply(invocation, tutor, refs, envelope, text=SAFE_TEXT, blocked=True, permit_solution=permit.solution)
        text = candidate.content
        if candidate.follow_up_question and candidate.follow_up_question not in text:
            text = f"{text.rstrip()}\n{candidate.follow_up_question}"
        work = verdict.effective_work_product
        remind = permit.must_remind_task and not work
        if remind and REMINDER not in text:
            text = f"{text.rstrip()}\n{REMINDER}"

        solution_after = permit.solution
        hint_index = None
        if work:
            solution_after, hint_index = self._apply_problem(
                tutor, problem_row, candidate, verdict, invocation, has_work_input=bool(content.strip() or images),
                summary=content,
            )
        message = TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=text)
        self.db.add(message)
        self.db.flush()
        payload = {"tutoring_session_id": tutor.id, "study_session_id": session.id}
        if work and candidate.student_turn_kind == "attempt":
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.attempt_recorded",
                source_type="tutoring_message", source_id=ward_msg.id, source="ward", visibility="ward",
                payload={**payload, "directive": directive},
            )
        if work and candidate.act in HINT_ACTS:
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.hint_given",
                source_type="tutoring_message", source_id=message.id, source="system",
                payload={**payload, "hint_index": hint_index},
            )
        if candidate.question_kind == "knowledge_lookup" and candidate.act not in {"clarify", "redirect", "pronounce"} and not work:
            publish_learning_fact(
                self.db, ward_id=session.ward_id, event_type="tutoring.curiosity_observed",
                source_type="tutoring_message", source_id=ward_msg.id, source="ward", visibility="ward", payload=payload,
            )
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=refs,
            next_interaction={
                "status": "needs_input", "content": text, "act": candidate.act,
                "hint_index": hint_index, "solution_state": solution_after, "safety_blocked": False,
                "return_to_task": remind, "model": settings.agent_model("tutoring"), "model_fallback": False,
            },
            context_snapshot=envelope.trace_snapshot(),
        )

    def _apply_problem(self, tutor, row, candidate, verdict, invocation, *, has_work_input, summary):
        """按 `TutorPermitPolicy.advance()` 推进题目记录。返回（答案状态，本轮提示序号）。

        同一个 Ward Turn 的重放不重复计数：记录已处理过本 turn 时原样返回。
        """
        if row is not None and candidate.same_problem and row.last_turn_id == invocation.turn_id:
            return row.solution_state, None
        if row is None or not candidate.same_problem:
            if row is not None:
                row.status = "abandoned"
            row = TutoringProblem(tutoring_session_id=tutor.id, summary=summary[:500])
            self.db.add(row)
            self.db.flush()
        assessment = ProblemAssessment(
            effective_work_product=True, student_turn_kind=candidate.student_turn_kind,
            progress=candidate.progress, same_problem=True, act=candidate.act,
            counts_as_attempt=has_work_input,
        )
        new = TutorPermitPolicy.advance(_state(row), assessment)
        _store(row, new)
        row.last_turn_id = invocation.turn_id
        return row.solution_state, (new.hints_given if candidate.act in HINT_ACTS else None)

    def _reply(self, invocation, tutor, refs, envelope, *, text, blocked, permit_solution):
        self.db.add(TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=text, safety_blocked=blocked))
        self.db.flush()
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=refs,
            next_interaction={
                "status": "needs_input", "content": text, "solution_state": permit_solution,
                "safety_blocked": blocked, "return_to_task": False,
                "model": settings.agent_model("tutoring"), "model_fallback": not blocked,
            },
            context_snapshot=envelope.trace_snapshot(),
        )

    def _ward_message(self, tutor, content):
        message = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content)
        self.db.add(message)
        self.db.flush()
        return message
