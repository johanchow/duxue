from __future__ import annotations

from app.contexts.study.domain.tutor_permit import (
    ProblemAssessment, ProblemState, TutorPermitPolicy,
)


def _turn(kind="attempt", progress=None, act="hint", work=True, same=True, counts=True):
    return ProblemAssessment(
        effective_work_product=work, student_turn_kind=kind, progress=progress,
        same_problem=same, act=act, counts_as_attempt=counts,
    )


def _run(*turns, state=None):
    for turn in turns:
        state = TutorPermitPolicy.advance(state, turn)
    return state


def test_a_new_problem_is_locked_and_without_a_task_there_is_no_reminder():
    permit = TutorPermitPolicy.permit(None, task_id=None, session_status="active", task_title=None)
    assert permit.solution == "locked"
    assert permit.must_remind_task is False
    assert permit.task_title is None


def test_a_task_session_asks_for_a_reminder_with_the_title():
    permit = TutorPermitPolicy.permit(None, task_id="t", session_status="paused", task_title="英语阅读")
    assert permit.must_remind_task is True
    assert permit.task_title == "英语阅读"
    assert TutorPermitPolicy.permit(None, task_id="t", session_status="finished", task_title="x").must_remind_task is False


def test_two_attempts_without_progress_unlock():
    state = _run(_turn(progress="none"))
    assert state.solution_state == "locked"
    state = _run(_turn(progress="none"), state=state)
    assert state.solution_state == "unlocked"
    assert state.no_progress_streak == 2


def test_progress_resets_the_streak_and_n_attempts_still_unlock():
    state = _run(_turn(progress="none"), _turn(progress="some"))
    assert state.no_progress_streak == 0 and state.solution_state == "locked"
    state = _run(_turn(progress="some"), state=state)
    assert state.substantive_attempts == 3 and state.solution_state == "unlocked"


def test_asking_for_the_answer_without_an_attempt_does_not_unlock():
    state = _run(*[_turn(kind="ask_answer", act="probe")] * 4)
    assert state.solution_state == "locked"
    assert state.substantive_attempts == 0
    assert state.answer_requested is True


def test_asking_for_the_answer_after_an_attempt_unlocks():
    state = _run(_turn(progress="some"), _turn(kind="ask_answer", act="probe"))
    assert state.solution_state == "unlocked"


def test_attempt_without_input_is_not_counted():
    state = _run(_turn(progress="none", counts=False))
    assert state.substantive_attempts == 0


def test_solved_is_terminal():
    state = _run(_turn(progress="solved"))
    assert state.solution_state == "solved" and state.status == "solved"


def test_hints_are_counted_and_other_acts_are_not():
    state = _run(_turn(kind="ask_hint", act="hint"), _turn(kind="ask_hint", act="probe"), _turn(kind="other", act="confirm"))
    assert state.hints_given == 2


def test_a_different_problem_starts_locked_and_empty():
    unlocked = ProblemState(solution_state="unlocked", substantive_attempts=3)
    state = TutorPermitPolicy.advance(unlocked, _turn(kind="ask_hint", same=False))
    assert state.solution_state == "locked" and state.substantive_attempts == 0


def test_a_turn_that_is_not_work_product_changes_nothing():
    state = ProblemState(substantive_attempts=1)
    assert TutorPermitPolicy.advance(state, _turn(work=False, kind="other", act="answer")) is state
