from __future__ import annotations
from datetime import date
from fastapi import HTTPException
from sqlalchemy.orm import Session
from ..ai_runtime.contracts import RunInvocation, WorkflowOutcome
from ..memory import record_learning_event
from ..models import FocusKit, Report, SelfReview, now

class ReflectionWorkflow:
    def __init__(self, db: Session): self.db = db
    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn
        if not turn.get("review_date") or not turn.get("review_feeling"):
            return WorkflowOutcome(run_status="waiting_for_ward", next_interaction={"status": "needs_self_review"})
        day = date.fromisoformat(turn["review_date"])
        review = self.db.query(SelfReview).filter_by(ward_id=invocation.ward_id, review_date=day).one_or_none()
        if review is None:
            review = SelfReview(ward_id=invocation.ward_id, review_date=day, feeling=turn["review_feeling"], reflection=turn.get("review_reflection"))
            self.db.add(review); self.db.flush()
        else:
            review.feeling, review.reflection = turn["review_feeling"], turn.get("review_reflection")
        record_learning_event(self.db, ward_id=invocation.ward_id, event_type="self_review.submitted", source_type="self_review", source_id=review.id, source_version=1, source="ward", payload={"review_date": day.isoformat(), "feeling": review.feeling})
        kit = self.db.query(FocusKit).filter_by(ward_id=invocation.ward_id, review_date=day).one_or_none()
        if turn.get("adopt_focus_kit"):
            if kit is None:
                kit = FocusKit(ward_id=invocation.ward_id, review_date=day, advice="下一次卡住时，先写下已知条件再继续。")
                self.db.add(kit)
                self.db.flush()
            kit.saved_at = now()
            record_learning_event(self.db, ward_id=invocation.ward_id, event_type="focus_kit.adopted", source_type="focus_kit", source_id=kit.id, source="ward", payload={"review_date": day.isoformat()})
        report = self.db.query(Report).filter_by(ward_id=invocation.ward_id, report_date=day).one_or_none()
        return WorkflowOutcome(run_status="closed", next_interaction={"status": "ready", "objective_evidence_status": "available" if report else "pending"})
