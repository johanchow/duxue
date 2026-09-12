from __future__ import annotations
from datetime import date
from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..ai_runtime.contracts import RunInvocation, WorkflowOutcome
from ..ai_runtime.context_builder import ContextBuilder
from ..ai_runtime.policy import PolicyRegistry
from ..ai_runtime.model_gateway import ModelGatewayError, QwenAgentModelGateway
from ..observability import record_llm_fallback
from ..config import settings
from ..integration_events import publish_learning_fact
from ..memory import SqlAlchemyMemoryFacade
from ..models import FocusKit, Report, SelfReview, now

class ReflectionWorkflow:
    def __init__(self, db: Session): self.db = db
    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn
        envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
            run_id=invocation.run_id, ward_id=invocation.ward_id, actor_id=invocation.ward_id,
            actor_role="ward", agent_type="reflection", context_refs=invocation.context_refs,
            context_spec=PolicyRegistry().context_spec("reflection"),
        )
        if not turn.get("review_date"):
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", next_interaction={"status": "needs_self_review"}, context_snapshot=envelope.trace_snapshot())
        day = date.fromisoformat(turn["review_date"])
        review = self.db.query(SelfReview).filter_by(ward_id=invocation.ward_id, review_date=day).one_or_none()
        if review is None and not turn.get("review_feeling"):
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", next_interaction={"status": "needs_self_review"}, context_snapshot=envelope.trace_snapshot())
        if review is None:
            review = SelfReview(ward_id=invocation.ward_id, review_date=day, feeling=turn["review_feeling"], reflection=turn.get("review_reflection"))
            self.db.add(review); self.db.flush()
        elif turn.get("review_feeling"):
            review.feeling, review.reflection = turn["review_feeling"], turn.get("review_reflection")
            review.version += 1
        if turn.get("review_feeling"):
            publish_learning_fact(self.db, ward_id=invocation.ward_id, event_type="self_review.submitted", source_type="self_review", source_id=review.id, source_version=review.version, source="ward", payload={"review_date": day.isoformat(), "feeling": review.feeling})
        kit = self.db.query(FocusKit).filter_by(ward_id=invocation.ward_id, review_date=day).one_or_none()
        if turn.get("adopt_focus_kit"):
            if kit is None:
                kit = FocusKit(ward_id=invocation.ward_id, review_date=day, advice="下一次卡住时，先写下已知条件再继续。")
                self.db.add(kit)
                self.db.flush()
            kit.saved_at = now()
            publish_learning_fact(self.db, ward_id=invocation.ward_id, event_type="focus_kit.adopted", source_type="focus_kit", source_id=kit.id, source="ward", payload={"review_date": day.isoformat()})
        report = self.db.query(Report).filter_by(ward_id=invocation.ward_id, report_date=day).one_or_none()
        advice = "下一次卡住时，先写下已知条件再继续。"
        model_fallback = False
        try:
            candidate = QwenAgentModelGateway().generate(
                agent_type="reflection", envelope=envelope.model_dump(),
                instruction=f"孩子的今日自评是：{review.feeling}。给一句积极、具体且不评价人格的复盘建议。",
            )
            if PolicyRegistry().validate_candidate(candidate.model_dump(), allowed_tools=set()).accepted:
                advice = candidate.content
        except ModelGatewayError as error:
            model_fallback = True
            record_llm_fallback(operation="agent_text", reason=str(error))
        return WorkflowOutcome(run_status="closed", outcome_type="completed", context_refs=[f"self_review:{review.id}"], next_interaction={"status": "ready", "objective_evidence_status": "available" if report else "pending", "advice": advice, "model": settings.agent_model("reflection"), "model_fallback": model_fallback}, context_snapshot=envelope.trace_snapshot())
