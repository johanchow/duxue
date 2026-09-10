from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..ai_runtime.contracts import RunInvocation, WorkflowOutcome
from ..memory import record_learning_event
from ..models import StudySession, TutoringMessage, TutoringSession, now

_DIRECT_ANSWER = re.compile(r"(直接.*答案|告诉我答案|选\s*[ABCD]|代写|写一篇作文)", re.I)


class TutoringWorkflow:
    """Safe deterministic fallback; a model may only replace its validated candidate."""
    def __init__(self, db: Session): self.db = db

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        turn = invocation.turn; session_id = turn.get("study_session_id")
        session = self.db.get(StudySession, session_id) if session_id else None
        if session_id is None:
            return WorkflowOutcome(run_status="waiting_for_ward", next_interaction={"status": "needs_study_session"})
        if session is None:
            raise HTTPException(404, "study session not found")
        if session.ward_id != invocation.ward_id:
            raise HTTPException(403, "study session does not belong to Ward")
        tutor = self.db.query(TutoringSession).filter_by(study_session_id=session.id).one_or_none()
        directive = turn.get("tutoring_directive") or "ask"
        if tutor is None and directive == "close":
            raise HTTPException(409, "there is no tutoring session to close")
        if tutor is None:
            tutor = TutoringSession(ward_id=session.ward_id, study_session_id=session.id, question_summary=turn.get("content", ""), model_name="deterministic-socratic-v1")
            self.db.add(tutor); self.db.flush()
        if tutor.status == "closed" and directive != "close": raise HTTPException(409, "tutoring session is closed")
        if directive == "close":
            if tutor.status != "closed":
                tutor.status = "closed"; tutor.closed_at = now()
            record_learning_event(self.db, ward_id=session.ward_id, event_type="tutoring.session_closed", source_type="tutoring_session", source_id=tutor.id, payload={"tutoring_session_id": tutor.id, "study_session_id": session.id})
            return WorkflowOutcome(run_status="closed", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "closed"})
        content = turn.get("content", "")
        blocked = bool(_DIRECT_ANSWER.search(content))
        ward = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content, is_stuck_point=True, safety_blocked=blocked)
        self.db.add(ward); self.db.flush()
        attempt_type = "tutoring.understanding_confirmed" if directive == "understood" else "tutoring.ward_attempt_recorded"
        record_learning_event(self.db, ward_id=session.ward_id, event_type=attempt_type, source_type="tutoring_message", source_id=ward.id, source="ward", visibility="ward", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "directive": directive})
        level = min(4, self.db.query(TutoringMessage).filter_by(tutoring_session_id=tutor.id, role="assistant").count() + 1)
        answer = "我会陪你一步步想，不直接给答案。先说说题目已知什么、要求什么？" if blocked else "先把题目的已知条件和要解决的问题分别写出来；你想先试哪一步？"
        hint = TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=answer, hint_level=level, safety_blocked=blocked)
        self.db.add(hint); self.db.flush()
        record_learning_event(self.db, ward_id=session.ward_id, event_type="tutoring.hint_given", source_type="tutoring_message", source_id=hint.id, source="system", payload={"tutoring_session_id": tutor.id, "study_session_id": session.id, "hint_level": level, "safety_blocked": blocked})
        return WorkflowOutcome(run_status="waiting_for_ward", context_refs=[f"tutoring_session:{tutor.id}"], next_interaction={"status": "needs_input", "content": answer, "hint_level": level, "safety_blocked": blocked})
