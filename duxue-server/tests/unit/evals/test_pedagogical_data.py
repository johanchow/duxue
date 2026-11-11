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
