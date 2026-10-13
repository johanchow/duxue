"""Evidence-driven answer protection for one tutoring problem.

This module deliberately has no dependency on Study, persistence, or an LLM.
It never unlocks an answer because of elapsed turns or failed attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

ProblemStatus = Literal["open", "submitted", "abandoned"]
# "Disclosure" is a separate state from "submission".  `submitted` records that the Ward handed in
# a proposal (the model's report, never a verdict).  Whether the answer may be shown is owned by this
# policy alone and is `protected` until a code rule releases it; no model field can do that.
Disclosure = Literal["protected", "released"]
PROTECTED_STATUSES = frozenset({"open", "submitted"})
HINT_ACTS = frozenset({"guide"})


@dataclass(frozen=True)
class ProblemState:
    status: ProblemStatus = "open"
    active_subgoal: str | None = None
    substantive_attempts: int = 0
    hints_given: int = 0
    evidence_summary: str | None = None
    disclosure: Disclosure = "protected"


@dataclass(frozen=True)
class AttemptSummary:
    substantive_attempts: int = 0
    hints_given: int = 0
    evidence_summary: str | None = None


@dataclass(frozen=True)
class TutorPermit:
    answer_protected: bool
    attempt_summary: AttemptSummary
    active_subgoal: str | None = None

    def as_context(self) -> dict:
        return {
            "answer_protected": self.answer_protected,
            "active_subgoal": self.active_subgoal,
            "attempt_summary": {
                "substantive_attempts": self.attempt_summary.substantive_attempts,
                "hints_given": self.attempt_summary.hints_given,
                "evidence_summary": self.attempt_summary.evidence_summary,
            },
        }


@dataclass(frozen=True)
class ProblemAssessment:
    """Only an already validated work-product turn on the current problem may reach this value
    object.  Switching to a new problem is decided by the caller before ``advance()``."""

    effective_work_product: bool
    student_move: str
    progress: str | None
    act: str
    counts_as_attempt: bool
    subgoal_evidence: str | None = None
    next_subgoal: str | None = None


class TutorPermitPolicy:
    @staticmethod
    def permit(problem: ProblemState | None) -> TutorPermit:
        if problem is None:
            return TutorPermit(False, AttemptSummary())
        return TutorPermit(
            answer_protected=problem.status in PROTECTED_STATUSES and problem.disclosure == "protected",
            active_subgoal=problem.active_subgoal if problem.status == "open" else None,
            attempt_summary=AttemptSummary(
                problem.substantive_attempts, problem.hints_given, problem.evidence_summary,
            ),
        )

    @staticmethod
    def advance(problem: ProblemState | None, assessment: ProblemAssessment) -> ProblemState | None:
        """Advance only from evidence; inability or a request never opens the answer."""
        if not assessment.effective_work_product:
            return problem
        if problem is None or problem.status != "open":
            problem = ProblemState()
        state = problem
        # A turn that receives the Ward's submission is not a hint.
        if assessment.act in HINT_ACTS and assessment.progress != "submitted":
            state = replace(state, hints_given=state.hints_given + 1)
        evidence = (assessment.subgoal_evidence or "").strip() or None
        if assessment.student_move != "attempt" or not assessment.counts_as_attempt or evidence is None:
            return state

        state = replace(
            state,
            substantive_attempts=state.substantive_attempts + 1,
            evidence_summary=evidence[:500],
        )
        # "submitted" is a student proposal, never a correctness verdict.
        if assessment.progress == "submitted":
            return replace(state, status="submitted", active_subgoal=None)
        next_subgoal = (assessment.next_subgoal or "").strip() or None
        if next_subgoal is not None:
            return replace(state, active_subgoal=next_subgoal[:300])
        return state
