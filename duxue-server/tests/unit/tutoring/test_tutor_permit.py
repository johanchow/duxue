from __future__ import annotations

from app.contexts.tutoring.domain.tutor_permit import (
    ProblemAssessment,
    ProblemState,
    TutorPermitPolicy,
)


def _turn(kind="attempt", progress=None, act="hint", work=True, same=True, counts=True, evidence=None, next_subgoal=None):
    return ProblemAssessment(
        effective_work_product=work, student_turn_kind=kind, progress=progress,
        same_problem=same, act=act, counts_as_attempt=counts,
        subgoal_evidence=evidence, next_subgoal=next_subgoal,
    )


def test_no_problem_is_unprotected_and_open_problem_is_protected():
    assert TutorPermitPolicy.permit(None).answer_protected is False
    permit = TutorPermitPolicy.permit(ProblemState(active_subgoal="先列出已知条件"))
    assert permit.answer_protected is True
    assert permit.active_subgoal == "先列出已知条件"


def test_any_number_of_requests_or_no_progress_never_unlocks_an_answer():
    state = None
    for _ in range(8):
        state = TutorPermitPolicy.advance(state, _turn(kind="ask_answer", act="probe"))
        state = TutorPermitPolicy.advance(state, _turn(progress="none", evidence="还是不知道从哪里开始"))
    assert state.status == "open"
    assert TutorPermitPolicy.permit(state).answer_protected is True


def test_evidence_advances_only_the_next_minimal_subgoal():
    state = ProblemState(active_subgoal="写出等式")
    state = TutorPermitPolicy.advance(
        state, _turn(progress="some", evidence="我写出 2x+3=9", next_subgoal="解出 x 的值"),
    )
    assert state.substantive_attempts == 1
    assert state.active_subgoal == "解出 x 的值"
    assert state.evidence_summary == "我写出 2x+3=9"


def test_attempt_without_evidence_does_not_advance_or_count():
    state = TutorPermitPolicy.advance(ProblemState(), _turn(progress="some"))
    assert state.substantive_attempts == 0
    assert state.active_subgoal is None


def test_full_student_proposal_is_submitted_not_marked_correct():
    state = TutorPermitPolicy.advance(
        ProblemState(active_subgoal="给出完整思路"),
        _turn(progress="solved", evidence="先移项再除以 2，所以 x=3"),
    )
    assert state.status == "submitted"
    assert TutorPermitPolicy.permit(state).answer_protected is False


def test_different_problem_starts_open_with_empty_progress():
    prior = ProblemState(active_subgoal="旧题", substantive_attempts=3, hints_given=2)
    state = TutorPermitPolicy.advance(prior, _turn(kind="ask_hint", same=False))
    assert state.status == "open"
    assert state.substantive_attempts == 0
    assert state.active_subgoal is None
