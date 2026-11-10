"""Single configuration ownership, production recovery and reproducible evaluation."""
import json
import os
import subprocess
import sys

import pytest
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.agent_specs.configuration import CODE_ROOT, read_snapshot, snapshot_bundle
from app.agent_specs.release_runtime import ReleaseRuntime


def test_production_has_contracts_but_no_editable_defaults():
    assert all(not (CODE_ROOT / name).exists() for name in ('agents', 'gates', 'tools'))
    ignored = (CODE_ROOT.parent / '.dockerignore').read_text().splitlines()
    assert 'var/' in ignored and 'tests/' in ignored
    contract = json.loads((CODE_ROOT / 'contracts.json').read_text())
    for doc in contract['files'].values():
        if 'prompt' in doc:
            assert 'template' not in doc['prompt']
            assert all('template' not in fragment for fragment in doc['prompt'].get('fragments', {}).values())
        assert 'static_result' not in doc
        assert all('name' not in model for model in doc.get('models', []))
    assert compile_bundle(snapshot_bundle()).bundle['compatibility'] == contract_compatibility(snapshot_bundle()['files'])


def test_missing_or_tampered_snapshot_never_falls_back(tmp_path):
    with pytest.raises(ValueError, match='快照不存在'):
        read_snapshot(tmp_path / 'missing.json')
    record = {'id': 'r1', 'digest': 'wrong', 'bundle': snapshot_bundle()}
    path = tmp_path / 'snapshot.json'; path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='摘要不匹配'):
        read_snapshot(path)


def test_production_explicitly_starts_admin_runtime(monkeypatch, tmp_path):
    from app.agent_specs import release_runtime
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('AGENT_CONFIG_SOURCE', 'admin')
    monkeypatch.setenv('AGENT_CONFIG_SOURCE_URL', 'http://private-admin/api/internal')
    monkeypatch.setenv('AGENT_ADMIN_INTERNAL_TOKEN', 'long-control-secret-at-least-32-characters')
    monkeypatch.setenv('AGENT_CONFIG_CACHE', str(tmp_path / 'release.json'))
    started = []
    monkeypatch.setattr(ReleaseRuntime, 'start', lambda self, **kwargs: started.append((self, kwargs)))
    monkeypatch.setattr(release_runtime, 'runtime', None)
    release_runtime.start_runtime()
    assert started[0][0].expected_environment == 'prod'
    assert started[0][1]['block'] is True
    monkeypatch.delenv('AGENT_ADMIN_INTERNAL_TOKEN')
    with pytest.raises(ValueError, match='通信密钥'):
        release_runtime.start_runtime()


def test_cached_release_survives_admin_failure_and_rejects_wrong_environment(monkeypatch, tmp_path):
    import httpx
    bundle = snapshot_bundle()
    for name in ('agents/tutoring.turn.json', 'agents/tutoring.image-target.json', 'gates/tutoring.leak-judge.json'):
        bundle['files'][name]['prompt']['template'] += '\n[image-review.v1]'
    compiled = compile_bundle(bundle)
    record = {'id': 'r1', 'digest': compiled.digest, 'bundle': bundle, 'environment': 'prod'}
    cache = tmp_path / 'cache.json'
    first = ReleaseRuntime('http://unused', 'token', cache, expected_environment='prod')
    first.accept(record)
    with pytest.raises(ValueError, match='环境不匹配'):
        first.accept({**record, 'environment': 'test'})
    with pytest.raises(ValueError, match='已发布'):
        first.accept({**record, 'kind': 'draft'})
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    recovered = ReleaseRuntime('http://unused', 'token', cache, expected_environment='prod')
    recovered.start()
    try:
        assert recovered.current[1].digest == compiled.digest
        assert recovered.definitions().artifact_digest == compiled.digest
        assert recovered.last_error == 'ConnectError'
    finally: recovered.close()
    assert cache.stat().st_mode & 0o777 == 0o600


def test_offline_evaluation_pins_all_threads_and_records_original_snapshot(tmp_path):
    bundle = snapshot_bundle(); compiled = compile_bundle(bundle)
    record = {'id': 'r1', 'digest': compiled.digest, 'bundle': bundle, 'environment': 'test'}
    path = tmp_path / 'release.json'; path.write_text(json.dumps(record))
    script = '''
import json,sys
from concurrent.futures import ThreadPoolExecutor
import evals.__main__ as cli
from evals.configuration import snapshot_identity

def check(args):
    from app.agent_specs.definitions import load_definitions
    from app.agent_specs.catalog import load_catalog
    before = load_definitions().artifact_digest
    # No reread, online polling or per-thread drift after evaluation begins.
    open(sys.argv[1], 'w').write('{}')
    with ThreadPoolExecutor(2) as pool:
        assert all(d == (before, before) for d in pool.map(
            lambda _: (load_definitions().artifact_digest, load_catalog().spec('tutoring').version), range(4)))
    assert snapshot_identity()['digest'] == before
    return 0
cli.cmd_run = check
assert cli.main(['run', '--component', 'companion.intent', '--config-snapshot', sys.argv[1]]) == 0
print('PASS')
'''
    env = {**os.environ, 'AGENT_CONFIG_SOURCE': 'admin', 'AGENT_CONFIG_SOURCE_URL': 'http://invalid.invalid'}
    result = subprocess.run([sys.executable, '-c', script, str(path)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PASS'


def test_admin_mode_does_not_silently_use_even_a_valid_offline_snapshot():
    script = """
from app.infrastructure.ai.components import COMPONENTS
from app.agent_specs.release_runtime import AgentConfigurationUnavailable
try:
    COMPONENTS.get('companion.intent')
except AgentConfigurationUnavailable:
    print('PASS')
else:
    raise AssertionError('Admin mode fell back to an offline configuration')
"""
    result = subprocess.run([sys.executable, '-c', script], env={**os.environ, 'AGENT_CONFIG_SOURCE':'admin'},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PASS'


def test_real_asgi_startup_without_local_defaults_and_http_cache_recovery(tmp_path):
    from app.agent_specs.configuration import snapshot_path
    record = json.loads(snapshot_path().read_text())
    for name in ('agents/tutoring.turn.json', 'agents/tutoring.image-target.json', 'gates/tutoring.leak-judge.json'):
        record['bundle']['files'][name]['prompt']['template'] += '\n[image-review.v1]'
    record['digest'] = compile_bundle(record['bundle']).digest
    source = tmp_path / 'configured-release.json'
    source.write_text(json.dumps(record))
    result = subprocess.run([sys.executable, 'scripts/admin_source_smoke.py', str(source)],
                            env={**os.environ, 'PYTHONPATH': '.'}, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert 'production ASGI startup' in result.stdout
    assert 'cold restart' in result.stdout


def test_workflows_have_no_production_copy_and_are_loaded_from_the_pinned_bundle():
    import copy

    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.definitions import use_definitions

    assert not (CODE_ROOT / 'workflows').exists()
    original = snapshot_bundle()
    changed = copy.deepcopy(original)
    # Order is observable in diagrams but does not alter execution behavior.
    changed['files']['workflows/reflection.json']['nodes'].reverse()
    changed['files']['workflows/reflection.json']['edges'].reverse()
    changed['compatibility'] = contract_compatibility(changed['files'])
    first, second = compile_bundle(original), compile_bundle(changed)
    with use_definitions(first.catalog):
        before = load_catalog()
        with use_definitions(second.catalog):
            after = load_catalog()
            assert after is not before
            assert after.spec('reflection').edges[0].target == 'END'
        assert load_catalog() is before
    with use_definitions(second.catalog):
        assert load_catalog() is after


@pytest.mark.parametrize('change', ['handler', 'reference', 'gate', 'limit', 'missing'])
def test_bundle_compilation_validates_workflows_without_local_topology(change):
    bundle = snapshot_bundle()
    flow = bundle['files']['workflows/tutoring-vet.json']
    if change == 'handler':
        flow['nodes'][-1]['handler_id'] = 'unregistered'
    elif change == 'reference':
        flow['nodes'][0]['ref'] = 'tutoring.missing'
    elif change == 'gate':
        flow['required_gates'] = []
    elif change == 'limit':
        flow['limits'] = {'model_calls': 100}
    else:
        del bundle['files']['workflows/tutoring-vet.json']
    bundle['compatibility'] = contract_compatibility(bundle['files'])
    with pytest.raises(ValueError):
        compile_bundle(bundle)


def test_release_workflow_execution_switch_and_rollback_keep_outer_call_pinned(tmp_path):
    import copy

    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.runtime import execute_workflow

    first = snapshot_bundle()
    second = copy.deepcopy(first)
    flow = second['files']['workflows/reflection.json']
    flow['nodes'].append({'id': 'reflection.extra', 'kind': 'action', 'handler_id': 'reflection.turn'})
    flow['edges'] = [{'from': 'START', 'to': 'reflection.turn'},
                     {'from': 'reflection.turn', 'to': 'reflection.extra'},
                     {'from': 'reflection.extra', 'to': 'END'}]
    second['compatibility'] = contract_compatibility(second['files'])
    one = {'id': 'first', 'bundle': first, 'digest': compile_bundle(first).digest}
    two = {'id': 'second', 'bundle': second, 'digest': compile_bundle(second).digest}
    runtime = ReleaseRuntime('http://unused', 'token', tmp_path / 'cache.json')

    def run():
        calls = []
        execute_workflow(load_catalog().spec('reflection'),
                         handlers={'reflection.turn': lambda state: calls.append('called')})
        return len(calls)

    runtime.accept(one)
    with runtime.pin():
        assert run() == 1
        runtime.accept(two)
        assert run() == 1
    with runtime.pin():
        assert run() == 2
    runtime.accept(one)
    with runtime.pin():
        assert run() == 1
    invalid = copy.deepcopy(two)
    invalid['bundle']['files']['workflows/reflection.json']['nodes'][0]['handler_id'] = 'unknown'
    invalid['bundle']['compatibility'] = contract_compatibility(invalid['bundle']['files'])
    with pytest.raises(ValueError, match='unknown action handler'):
        runtime.accept(invalid)
    assert json.loads(runtime.cache.read_text())['id'] == 'first'


def test_tutor_call_limits_follow_selected_workflow_instead_of_import_time_defaults():
    from types import SimpleNamespace

    from app.agent_specs.definitions import use_definitions
    from app.application.workflows.tutor_loop import call_tutor_model

    bundle = snapshot_bundle()
    bundle['files']['workflows/tutoring.json']['limits'] = {'model_calls': 2, 'tool_calls': 1}
    bundle['compatibility'] = contract_compatibility(bundle['files'])
    compiled = compile_bundle(bundle)
    model_calls, tool_calls = [], []

    def complete(**kwargs):
        model_calls.append(1)
        return {'tool': 'lookup_history', 'args': {}}

    def run(name, args):
        tool_calls.append(name)
        return {'tool': name, 'status': 'no_match'}

    with use_definitions(compiled.catalog):
        call_tutor_model(SimpleNamespace(complete=complete), {}, '', [], [], SimpleNamespace(run=run))
    assert len(model_calls) == 2
    assert tool_calls == ['lookup_history']


@pytest.mark.parametrize('change', ['missing_limits', 'spoofed_check', 'judge_as_agent'])
def test_bundle_rejects_missing_budgets_and_relabelled_safety_nodes(change):
    bundle = snapshot_bundle()
    flow = bundle['files']['workflows/tutoring.json']
    if change == 'missing_limits':
        del flow['limits']
    elif change == 'spoofed_check':
        next(node for node in flow['nodes'] if node['id'] == 'tutoring.output_safety')['ref'] = 'tutoring.visual'
    else:
        node = bundle['files']['workflows/tutoring-vet.json']['nodes'][1]
        node['kind'] = 'agent'
    bundle['compatibility'] = contract_compatibility(bundle['files'])
    with pytest.raises(ValueError):
        compile_bundle(bundle)


def test_eager_workflow_validation_keeps_existing_authorized_tool_subset_editable():
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.definitions import use_definitions

    bundle = snapshot_bundle()
    bundle['files']['agents/tutoring.turn.json']['tools'].remove('tutoring.lookup_history')
    compiled = compile_bundle(bundle)
    with use_definitions(compiled.catalog):
        assert load_catalog().spec('tutoring').id == 'tutoring'
        assert 'tutoring.lookup_history' not in compiled.catalog.units['tutoring.turn'].tools


def test_image_review_output_budget_can_fit_a_full_page_without_becoming_unbounded():
    import pytest
    from app.agent_specs.definitions import ModelDefinition
    from pydantic import ValidationError
    values = dict(name='model', component_id='tutoring.turn', timeout_ms=120000,
                  temperature=0, max_output_tokens=8192)
    assert ModelDefinition.model_validate(values).max_output_tokens == 8192
    with pytest.raises(ValidationError):
        ModelDefinition.model_validate({**values, 'max_output_tokens': 16385})
