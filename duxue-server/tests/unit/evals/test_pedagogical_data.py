"""Imported checkpoints preserve fixed history and isolate grading references."""

from evals import dataset
from evals.dialogue import TurnRecord


def test_adapted_checkpoints_exclude_source_prompts_and_target_completions():
    records = [
        TurnRecord.model_validate(dataset.read_object(p))
        for p in dataset.DATA_DIR.rglob('pedagogy-*.json')
    ]
    assert len(records) == 5
    for record in records:
        assert record.label_status == 'proposed'
        assert record.source.kind == 'synthetic'
        assert record.source.provider
        assert record.checks[0].after_message == record.messages[-1].id
        assert record.messages[-1].role == 'user'
        case = record.to_case()
        assert case.snapshot_origin == 'synthetic'
        assert len(case.history) <= 8
        assert all(m.role in {'user', 'assistant'} for m in record.messages)
        assert 'original_system' in record.source.note
        assert 'original_system' not in str(case.model_dump())
        assert case.grading.model_graded


def test_multiturn_sources_keep_prior_replies_but_only_evaluate_last_request():
    cases = {c.id: c for c in dataset.load_cases()}
    brownie = cases['pedagogy-brownies-confirmation']
    adjective = cases['pedagogy-adjective-feedback']
    assert len(brownie.history) == len(adjective.history) == 8
    assert brownie.history[-1].author == 'companion'
    assert '20 brownies' in brownie.student_said
    assert 'comfortable, incredible' in adjective.student_said
    assert 'participle adjectives' not in str(adjective.history)
    assert 'Excellent job! So now we know' not in str(brownie.history)


def test_subject_batch_contains_only_three_text_questions_and_no_completions():
    from evals.__main__ import main

    cases = [c for c in dataset.load_cases() if c.review_batch == 'subject-competence-v1']
    assert {c.id for c in cases} == {
        'subject-portraits-next-step',
        'subject-reading-evidence',
        'subject-rhetoric-distinction',
    }
    for case in cases:
        assert case.label_status == 'proposed'
        assert case.snapshot_origin == 'synthetic'
        assert case.history == []
        assert case.images == []
        assert case.context.problem.substantive_attempts == 0
        assert case.grading.reference_response is None
        record = dataset.read_object(next(dataset.DATA_DIR.rglob(case.id + '.json')))
        assert len(record['messages']) == 1
        assert record['messages'][0]['role'] == 'user'
        assert record['source']['provider'] != 'essay-asap'
        assert record['source']['note'].split('original_system')[0] not in case.student_said
    assert main(['validate', '--batch', 'subject-competence-v1']) == 0
