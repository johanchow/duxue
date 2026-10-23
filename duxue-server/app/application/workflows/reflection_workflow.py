from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.queries.context_builder import ContextBuilder
from app.contexts.companion.domain.policy import PolicyRegistry
from app.application.commands.self_reviews import confirm_self_review
from app.infrastructure.observability.telemetry import traced_agent_node
from app.infrastructure.persistence.models import Report, SelfReview

_SELF_REVIEW_PROMPT = "如果想复盘今天的学习，请先说说今天学了什么、感觉如何；想问其他问题也可以直接问我。"

class ReflectionWorkflow:
    def __init__(self, db: Session): self.db = db
    @traced_agent_node("reflection.turn")
    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn
        envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.db)).build(
            run_id=invocation.run_id, ward_id=invocation.ward_id, actor_id=invocation.ward_id,
            actor_role="ward", agent_type="reflection", context_refs=invocation.context_refs,
            context_spec=PolicyRegistry().context_spec("reflection"),
        )
        if not turn.get("review_date"):
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", next_interaction={"status": "needs_self_review", "content": _SELF_REVIEW_PROMPT}, context_snapshot=envelope.trace_snapshot())
        day = date.fromisoformat(turn["review_date"])
        review = self.db.query(SelfReview).filter_by(ward_id=invocation.ward_id, review_date=day).one_or_none()
        if review is None and not turn.get("review_feeling"):
            return WorkflowOutcome(run_status="waiting_for_ward", outcome_type="waiting", next_interaction={"status": "needs_self_review", "content": _SELF_REVIEW_PROMPT}, context_snapshot=envelope.trace_snapshot())
        if review is None:
            review = confirm_self_review(
                self.db, ward_id=invocation.ward_id, review_date=day,
                raw_expression=turn.get("review_reflection") or turn["review_feeling"],
                aspects=[], expected_version=0, feeling=turn["review_feeling"],
            )
        elif turn.get("review_feeling"):
            review = confirm_self_review(
                self.db, ward_id=invocation.ward_id, review_date=day,
                raw_expression=turn.get("review_reflection") or turn["review_feeling"],
                aspects=[], expected_version=review.version, feeling=turn["review_feeling"],
            )
        report = self.db.query(Report).filter_by(ward_id=invocation.ward_id, report_date=day).one_or_none()
        return WorkflowOutcome(
            run_status="closed", outcome_type="completed",
            context_refs=[f"self_review:{review.id}"],
            next_interaction={
                "status": "ready",
                "objective_evidence_status": "available" if report else "pending",
                "content": "我记下了你的今日总结。" if report else "我记下了你的今日总结，观察记录还在整理中。",
            },
            context_snapshot=envelope.trace_snapshot(),
        )
