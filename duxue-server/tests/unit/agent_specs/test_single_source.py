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
    assert compile_bundle(snapshot_bundle()).bundle['compatibility'] == contract_compatibility()


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
    bundle = snapshot_bundle(); compiled = compile_bundle(bundle)
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
    before = load_definitions().artifact_digest
    # No reread, online polling or per-thread drift after evaluation begins.
    open(sys.argv[1], 'w').write('{}')
    with ThreadPoolExecutor(2) as pool:
        assert all(d == before for d in pool.map(lambda _: load_definitions().artifact_digest, range(4)))
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


def test_real_asgi_startup_without_local_defaults_and_http_cache_recovery():
    from app.agent_specs.configuration import snapshot_path
    result = subprocess.run([sys.executable, 'scripts/admin_source_smoke.py', str(snapshot_path())],
                            env={**os.environ, 'PYTHONPATH': '.'}, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert 'production ASGI startup' in result.stdout
    assert 'cold restart' in result.stdout
