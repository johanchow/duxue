"""Judge semantic facts map to stable protocol reasons; no text heuristics."""
import pytest
from app.agent_specs.verdicts import normalize_judge

from tests.support.fakes import leak_judge_facts as facts


@pytest.mark.parametrize('changes, expected', [
    ({}, 'none'),
    ({'student_answer_correct': False}, 'none'),  # Questioning an incorrect answer is allowed.
    ({'student_answer_correct': True, 'affirms_student_answer': True}, 'none'),
    ({'affirms_student_answer': True}, 'incorrect_confirmation'),
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
    for payload in ({'new_final_answer': False}, {**facts(), 'new_final_answer': 'false'}):
        assert normalize_judge('tutoring.leak-judge', payload).verdict == 'unknown'
