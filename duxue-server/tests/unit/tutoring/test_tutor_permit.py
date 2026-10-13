from __future__ import annotations

from dataclasses import replace

from app.contexts.tutoring.domain.tutor_permit import (
    ProblemAssessment,
    ProblemState,
    TutorPermitPolicy,
)


def _turn(kind="attempt", progress=None, act="guide", work=True, counts=True, evidence=None, next_subgoal=None):
    return ProblemAssessment(
        effective_work_product=work, student_move=kind, progress=progress,
        act=act, counts_as_attempt=counts,
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
        state = TutorPermitPolicy.advance(state, _turn(kind="request_answer"))
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
        _turn(progress="submitted", evidence="先移项再除以 2，所以 x=3"),
    )
    assert state.status == "submitted"
    # 提交只是孩子的提议：不等于允许披露答案，披露由代码策略（disclosure）独占。
    assert TutorPermitPolicy.permit(state).answer_protected is True
    released = replace(state, disclosure="released")
    assert TutorPermitPolicy.permit(released).answer_protected is False
    assert TutorPermitPolicy.permit(replace(state, status="abandoned")).answer_protected is False


def test_a_turn_after_a_submission_starts_a_fresh_open_problem():
    prior = ProblemState(status="submitted", substantive_attempts=3, hints_given=2)
    state = TutorPermitPolicy.advance(prior, _turn(kind="request_hint"))
    assert state.status == "open"
    assert state.substantive_attempts == 0
    assert state.hints_given == 1
    assert state.active_subgoal is None


def test_only_guide_counts_as_a_hint_and_a_submission_does_not():
    state = TutorPermitPolicy.advance(None, _turn(kind="request_hint", act="guide"))
    assert state.hints_given == 1
    assert TutorPermitPolicy.advance(state, _turn(kind="request_hint", act="chat")).hints_given == 1
    submitted = TutorPermitPolicy.advance(state, _turn(progress="submitted", evidence="x=3"))
    assert submitted.hints_given == 1 and submitted.status == "submitted"
