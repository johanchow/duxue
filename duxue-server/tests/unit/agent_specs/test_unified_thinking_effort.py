"""All configured model components share one provider-independent effort setting."""
import pytest

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.configuration import snapshot_bundle
from app.agent_specs.definitions import ModelDefinition, use_definitions
from app.agent_specs.verdicts import normalize_judge
from app.infrastructure.ai.components import COMPONENTS
from tests.support.fakes import leak_judge_facts


@pytest.mark.parametrize('effort', ['off', 'low', 'medium', 'high'])
def test_effort_compiles_for_every_model_and_reaches_registry(effort):
    bundle = snapshot_bundle()
    for doc in bundle['files'].values():
        for model in doc.get('models', []):
            for key in ('enable_thinking', 'thinking_budget', 'guardian_t1_reasoning_effort'):
                model.pop(key, None)
            model['thinking_effort'] = effort
    assert bundle['compatibility'] == contract_compatibility(bundle['files'])
    compiled = compile_bundle(bundle)
    with use_definitions(compiled.catalog):
        assert all(spec.thinking_effort == effort for spec in COMPONENTS.all())


def test_unknown_correctness_is_not_an_explicit_violation():
    result = normalize_judge('tutoring.leak-judge', leak_judge_facts(
        affirms_student_answer=True, student_answer_correct=None,
    ))
    assert result.verdict == 'allow'


def test_upgrade_migrates_every_model_and_disables_judge_thinking():
    from scripts.upgrade_unified_thinking_effort import upgrade

    bundle = snapshot_bundle()
    original = {'bundle': bundle, 'digest': compile_bundle(bundle).digest}
    updated = upgrade(original)
    for doc in updated['bundle']['files'].values():
        for model in doc.get('models', []):
            assert model['thinking_effort'] in {'off', 'low', 'medium', 'high'}
            assert not {'enable_thinking', 'thinking_budget', 'guardian_t1_reasoning_effort'} & model.keys()
    judge = updated['bundle']['files']['gates/tutoring.leak-judge.json']
    assert all(model['thinking_effort'] == 'off' for model in judge['models'])
    intent = updated['bundle']['files']['agents/companion.intent.json']
    assert 'thinking_effort' in intent['output_schema']['properties']
    assert 'thinking' not in intent['output_schema']['properties']
    assert upgrade(updated)['bundle'] == updated['bundle']


def test_canonical_model_serialization_round_trips_without_legacy_fields():
    model = ModelDefinition(
        component_id='companion.intent', name='qwen3.7-flash',
        temperature=0, timeout_ms=10000, max_output_tokens=100,
        thinking_effort='off',
    )
    data = model.model_dump(mode='json')
    assert 'enable_thinking' not in data
    assert ModelDefinition.model_validate(data).thinking_effort == 'off'
