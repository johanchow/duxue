"""Local Admin must not inherit business credentials from Server's .env."""
import runpy
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[4] / 'duxue-admin/scripts/start_server.py'


def test_local_executor_uses_own_env_and_isolates_business_dependencies(tmp_path):
    build = runpy.run_path(str(script))['executor_environment']
    root = tmp_path / 'duxue-admin'
    root.mkdir()
    token = 'local-test-control-token-at-least-32-characters'
    (root / '.env').write_text(f'AGENT_ADMIN_INTERNAL_TOKEN={token}\nVLM_API_KEY=test-key\n')
    (root / '.env.local').write_text('VLM_API_KEY=wrong-legacy-key\n')
    env = build(root, {'DATABASE_URL': 'postgresql://unused-business', 'REDIS_URL': 'redis://business'})
    assert env['VLM_API_KEY'] == 'test-key'
    assert env['JWT_SECRET_KEY'] == token
    assert env['ENV_FILE'] == str(root / '.env')
    assert env['DATABASE_URL'] == 'sqlite:///:memory:'
    assert env['REDIS_URL'] == 'redis://unused:6379/0'
    assert env['AGENT_CONFIG_SOURCE_URL'] == ''
    assert env['APP_ENV'] == 'test'
    assert build(root, {'VLM_API_KEY': 'injected-key'})['VLM_API_KEY'] == 'injected-key'
    with pytest.raises(RuntimeError, match='仅用于本机测试环境'):
        build(root, {'ADMIN_ENV': 'prod'})
    with pytest.raises(RuntimeError, match='VLM_API_KEY'):
        build(root, {'VLM_API_KEY': ''})
