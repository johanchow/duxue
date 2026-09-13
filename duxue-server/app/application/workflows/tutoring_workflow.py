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
from app.infrastructure.persistence.models import StudySession, TutoringMessage, TutoringSession, now

class TutoringWorkflow:
    """Safe deterministic fallback; a model may only replace its validated candidate."""
    def __init__(self, db: Session): self.db = db

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn; session_id = turn.get("study_session_id")
        policy = PolicyRegistry()
        envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
            run_id=invocation.run_id, ward_id=invocation.ward_id, actor_id=invocation.ward_id,
            actor_role="ward", agent_type="tutoring", context_refs=invocation.context_refs,
            context_spec=policy.context_spec("tutoring"),
        )
        session = self.db.get(StudySession, session_id) if session_id else None
        if session_id is None:
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", next_interaction={"status": "needs_study_session"}, context_snapshot=envelope.trace_snapshot())
        if session is None:
            raise HTTPException(404, "study session not found")
        if session.ward_id != invocation.ward_id:
            raise HTTPException(403, "study session does not belong to Ward")
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
        decision = policy.validate_tutoring_input(content)
        blocked = not decision.accepted
        ward = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content, is_stuck_point=True, safety_blocked=blocked)
        self.db.add(ward); self.db.flush()
        attempt_type = "tutoring.understanding_confirmed" if directive == "understood" else "tutoring.ward_attempt_recorded"
        publish_learning_fact(self.db, ward_id=session.ward_id, event_type=attempt_type, source_type="tutoring_message", source_id=ward.id, source="ward", visibility="ward", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "directive": directive})
        level = min(4, self.db.query(TutoringMessage).filter_by(tutoring_session_id=tutor.id, role="assistant").count() + 1)
        answer = decision.safe_response if blocked else "先把题目的已知条件和要解决的问题分别写出来；你想先试哪一步？"
        model_fallback = False
        if not blocked:
            try:
                candidate = QwenAgentModelGateway().generate(
                    agent_type="tutoring", envelope=envelope.model_dump(),
                    instruction=f"孩子刚才说：{content!r}。请给一条不直接给答案的启发式回应。",
                )
                policy_result = policy.validate_candidate(candidate.model_dump(), allowed_tools=set())
                if policy_result.accepted:
                    answer = candidate.content
            except ModelGatewayError as error:
                model_fallback = True
                record_llm_fallback(operation="agent_text", reason=str(error))
        hint = TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=answer, hint_level=level, safety_blocked=blocked)
        self.db.add(hint); self.db.flush()
        publish_learning_fact(self.db, ward_id=session.ward_id, event_type="tutoring.hint_given", source_type="tutoring_message", source_id=hint.id, source="system", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "hint_level": level, "safety_blocked": blocked})
        return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "needs_input", "content": answer, "hint_level": level, "safety_blocked": blocked, "model": settings.agent_model("tutoring"), "model_fallback": model_fallback}, context_snapshot=envelope.trace_snapshot())
