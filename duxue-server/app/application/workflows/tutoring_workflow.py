from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.queries.context_builder import ContextBuilder
from app.contexts.companion.domain.policy import PolicyRegistry
from app.infrastructure.ai.model_gateway import ModelGatewayError, QwenAgentModelGateway
from app.infrastructure.observability.telemetry import record_llm_fallback
from app.bootstrap.settings import settings
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.contexts.study.domain.execution import HintingPolicy
from app.infrastructure.persistence.models import StudySession, StudySessionInterval, TutoringMessage, TutoringSession, now

class TutoringWorkflow:
    """Safe deterministic fallback; a model may only replace its validated candidate."""
    def __init__(self, db: Session): self.db = db

    def _open_session(self, ward_id: str, session_id: str | None) -> StudySession:
        if session_id:
            session = self.db.get(StudySession, session_id)
            if session is None:
                raise HTTPException(404, "study session not found")
            if session.ward_id != ward_id:
                raise HTTPException(403, "study session does not belong to Ward")
            return session
        session = (
            self.db.query(StudySession)
            .filter(StudySession.ward_id == ward_id, StudySession.status.in_(("active", "paused")))
            .order_by(StudySession.started_at.desc())
            .first()
        )
        if session is not None:
            return session
        session = StudySession(ward_id=ward_id, task_id=None, status="active")
        self.db.add(session)
        self.db.flush()
        self.db.add(StudySessionInterval(study_session_id=session.id))
        publish_learning_fact(
            self.db, ward_id=ward_id, event_type="study_session.started",
            source_type="study_session", source_id=session.id, payload={"task_id": None},
        )
        return session

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        if invocation.turn.get("tutoring_intent") == "pronunciation":
            from app.application.workflows.pronunciation_guidance import PronunciationGuidance
            return PronunciationGuidance(self.db).present(invocation)
        turn = invocation.turn; session_id = turn.get("study_session_id")
        policy = PolicyRegistry()
        envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
            run_id=invocation.run_id, ward_id=invocation.ward_id, actor_id=invocation.ward_id,
            actor_role="ward", agent_type="tutoring", context_refs=invocation.context_refs,
            context_spec=policy.context_spec("tutoring"),
        )
        session = self._open_session(invocation.ward_id, session_id)
        tutor = self.db.query(TutoringSession).filter_by(study_session_id=session.id).one_or_none()
        directive = turn.get("tutoring_directive") or "ask"
        if tutor is None and directive == "close":
            raise HTTPException(409, "there is no tutoring session to close")
        if tutor is None:
            tutor = TutoringSession(ward_id=session.ward_id, study_session_id=session.id, question_summary=turn.get("content", ""), model_name=settings.agent_model("tutoring"))
            self.db.add(tutor); self.db.flush()
        if tutor.status == "closed" and directive != "close": raise HTTPException(409, "tutoring session is closed")
        if directive == "close":
            if tutor.status != "closed":
                tutor.status = "closed"; tutor.closed_at = now()
            publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.session_closed", source_type="tutoring_session", source_id=tutor.id, payload={"tutoring_session_id": tutor.id, "study_session_id": session.id})
            return WorkflowOutcome(run_status="closed", outcome_type="completed", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "closed"}, context_snapshot=envelope.trace_snapshot())
        content = turn.get("content", "")
        input_decision = policy.validate_tutoring_input(content)
        blocked = not input_decision.accepted
        label = "answer_seeking" if blocked else turn.get("intent_label") or "problem"
        prior_attempts = self.db.query(TutoringMessage).filter_by(tutoring_session_id=tutor.id, role="ward", safety_blocked=False).count()
        # 新提问从 L1 开始。只有「再试一次 / 继续求提示」才沿用同一题的尝试次数。
        failed_attempts = 0 if directive == "ask" else prior_attempts
        hinting = HintingPolicy.evaluate(failed_attempts=failed_attempts, intent_label=label, has_task=bool(session.task_id), session_status=session.status)
        ward = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content, is_stuck_point=label == "problem", safety_blocked=blocked)
        self.db.add(ward); self.db.flush()
        if directive == "understood":
            publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.understanding_confirmed", source_type="tutoring_message", source_id=ward.id, source="ward", visibility="ward", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id})
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "understood", "hint_level": hinting.allowed_level, "safety_blocked": False}, context_snapshot=envelope.trace_snapshot())
        if hinting.record_fact and label == "curiosity":
            publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.curiosity_observed", source_type="tutoring_message", source_id=ward.id, source="ward", visibility="ward", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id})
        elif hinting.record_fact:
            publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.attempt_recorded", source_type="tutoring_message", source_id=ward.id, source="ward", visibility="ward", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "directive": directive})
        level = hinting.allowed_level
        answer = input_decision.safe_response if blocked else _fallback_hint(level, hinting.l4_walkthrough_allowed)
        model_fallback = False
        if not blocked:
            try:
                candidate = QwenAgentModelGateway().generate(
                    agent_type="tutoring", envelope=envelope.model_dump(),
                    instruction=f"孩子刚才说：{content!r}。请给一条不超过 L{level} 的启发式回应。",
                )
                policy_result = policy.validate_candidate(candidate.model_dump(), allowed_tools=set())
                if policy_result.accepted and HintingPolicy.accepts_display(hinting, candidate.content):
                    answer = candidate.content
            except ModelGatewayError as error:
                model_fallback = True
                record_llm_fallback(operation="agent_text", reason=str(error))
        if hinting.return_to_task:
            reminder = "先回到正在进行的任务，这个问题可以稍后再问。"
            if reminder not in answer:
                answer = f"{answer.rstrip()}\n{reminder}"
        hint = TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=answer, hint_level=level, safety_blocked=blocked)
        self.db.add(hint); self.db.flush()
        if hinting.record_fact and label != "curiosity":
            publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.hint_given", source_type="tutoring_message", source_id=hint.id, source="system", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "hint_level": level})
        return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "needs_input", "content": answer, "hint_level": level, "safety_blocked": blocked, "return_to_task": hinting.return_to_task, "model": settings.agent_model("tutoring"), "model_fallback": model_fallback}, context_snapshot=envelope.trace_snapshot())


def _fallback_hint(level: int, l4_allowed: bool) -> str:
    if level >= 4 and l4_allowed:
        return "我们把已知条件和下一步对应起来。如果换一个更小的数字，这一步还成立吗？用这个验证问题自己再算一次。"
    return "先把题目的已知条件和要解决的问题分别写出来；你想先试哪一步？"
