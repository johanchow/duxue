"""Judge semantic facts map to stable protocol reasons; no text heuristics."""
import pytest

from app.agent_specs.verdicts import normalize_judge
from tests.support.fakes import leak_judge_facts as facts


@pytest.mark.parametrize('changes, expected', [
    ({}, 'none'),
    ({'student_answer_correct': False}, 'none'),  # Questioning an incorrect answer is allowed.
    ({'student_answer_correct': True, 'affirms_student_answer': True}, 'none'),
    ({'student_answer_correct': 'partial', 'affirms_student_answer': True}, 'none'),
    ({'affirms_student_answer': True}, 'none'),
    ({'student_answer_correct': False, 'affirms_student_answer': True}, 'incorrect_confirmation'),
    ({'new_final_answer': True}, 'final_answer'),
    ({'new_final_answer': True, 'affirms_student_answer': True}, 'final_answer'),
    ({'complete_solution': True}, 'complete_solution'),
    ({'choice_verdict': True, 'new_final_answer': True}, 'choice_verdict'),
    ({'premature_conclusion': True}, 'premature_conclusion'),
])
def test_judge_facts_derive_verdict_and_specific_reason(changes, expected):
    payload = facts()
    payload.update(changes)
    result = normalize_judge('tutoring.leak-judge', payload)
    assert result.reason_code == expected
    assert result.verdict == ('allow' if expected == 'none' else 'deny')


def test_incomplete_or_non_boolean_judgments_fail_closed():
    for payload in (
        {'new_final_answer': False},
        {**facts(), 'new_final_answer': 'false'},
        {**facts(), 'student_answer_correct': 'maybe'},
        {**facts(), 'student_answer_correct': 1},
    ):
        assert normalize_judge('tutoring.leak-judge', payload).verdict == 'unknown'


def test_judge_requires_explicit_turn_scope_and_rejects_conflicting_facts():
    payload = facts()
    payload.pop('answer_protected', None)
    assert normalize_judge('tutoring.leak-judge', payload).verdict == 'unknown'
    assert normalize_judge('tutoring.leak-judge', {
        **facts(), 'answer_protected': False, 'new_final_answer': True,
    }).verdict == 'unknown'


def test_independent_non_reasoning_scope_is_allowed():
    assert normalize_judge('tutoring.leak-judge', facts(answer_protected=False)).verdict == 'allow'


def test_non_protected_practice_allows_verified_student_affirmation():
    result = normalize_judge('tutoring.leak-judge', facts(
        answer_protected=False, student_answer_correct=True, affirms_student_answer=True,
    ))
    assert result.verdict == 'allow'
    assert result.reason_code == 'none'


def test_non_protected_practice_still_rejects_unverified_affirmation():
    result = normalize_judge('tutoring.leak-judge', facts(
        answer_protected=False, student_answer_correct=False, affirms_student_answer=True,
    ))
    assert result.verdict == 'deny'
    assert result.reason_code == 'incorrect_confirmation'


def test_evidence_phase_ignores_reply_leak_flags_and_enforces_premature_conclusion():
    # In evidence_only phase, reply is empty (""): spurious choice_verdict / new_final_answer
    # from the judge must not reject the evidence report.
    allowed = normalize_judge(
        'tutoring.leak-judge',
        facts(choice_verdict=True, new_final_answer=True, complete_solution=True, premature_conclusion=False),
        phase='evidence',
    )
    assert allowed.verdict == 'allow'
    assert allowed.reason_code == 'none'

    # Factual report defects (premature_conclusion=True) still reject in evidence phase.
    denied = normalize_judge(
        'tutoring.leak-judge',
        facts(premature_conclusion=True),
        phase='evidence',
    )
    assert denied.verdict == 'deny'
    assert denied.reason_code == 'premature_conclusion'
