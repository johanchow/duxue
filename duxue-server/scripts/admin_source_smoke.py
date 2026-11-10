"""Isolated ASGI + real HTTP source/cache smoke, without business DB or provider calls."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    record = json.loads(sys.stdin.read()) if sys.argv[1] == '-' else json.loads(Path(sys.argv[1]).read_text())
    token = 'isolated-source-smoke-secret-at-least-32-characters'
    state = {'release': record, 'available': True, 'acks': []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers['Authorization'] == 'Bearer ' + token
            self.send_response(200 if state['available'] else 503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'environment': 'prod', 'release': state['release']}).encode())

        def do_POST(self):
            assert self.headers['Authorization'] == 'Bearer ' + token
            state['acks'].append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix='agent-source-smoke-') as directory:
        cache = Path(directory) / 'last-good.json'
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        os.environ.update({
            'ENV_FILE': '/dev/null', 'APP_ENV': 'production', 'DATABASE_URL': 'sqlite:///:memory:',
            'JWT_SECRET_KEY': token, 'REDIS_HOST': 'unused', 'REDIS_URL': 'redis://unused',
            'VLM_API_KEY': 'unused-smoke-key', 'STORAGE_BACKEND': 'local',
            'LOCAL_UPLOAD_DIR': str(Path(directory) / 'uploads'),
            'OTEL_SDK_DISABLED': 'true', 'LANGFUSE_ENABLED': 'false', 'AI_MODEL_OVERRIDES': '',
            'AGENT_CONFIG_SOURCE': 'admin', 'AGENT_ADMIN_INTERNAL_TOKEN': token,
            'AGENT_CONFIG_SOURCE_URL': f'http://127.0.0.1:{server.server_port}/api/internal',
            'AGENT_CONFIG_CACHE': str(cache),
        })
        from fastapi.testclient import TestClient

        from app.agent_specs import release_runtime
        from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
        from app.agent_specs.catalog import load_catalog
        from app.bootstrap.app import app
        from app.infrastructure.ai.components import COMPONENTS

        try:
            before = len(state['acks'])
            check = subprocess.run([sys.executable, '-m', 'app.agent_specs', 'preflight'], capture_output=True, text=True, check=False)
            assert check.returncode == 0, check.stderr
            assert len(state['acks']) == before, 'Preflight must not register a serving instance'
            with TestClient(app) as client:
                assert client.get('/health').status_code == 200
                runtime = release_runtime.runtime
                assert runtime.current[1].digest == record['digest']
                original = COMPONENTS.get('companion.intent').prompt.text
                original_flow = load_catalog().spec('reflection')
                replacement = copy.deepcopy(record)
                replacement['id'] = '00000000-0000-4000-8000-000000000002'
                replacement['bundle']['files']['agents/companion.intent.json']['prompt']['template'] += '\nSmoke version.'
                replacement['bundle']['files']['workflows/reflection.json']['edges'].reverse()
                replacement['bundle']['compatibility'] = contract_compatibility(replacement['bundle']['files'])
                replacement['digest'] = compile_bundle(replacement['bundle']).digest
                with runtime.pin():
                    state['release'] = replacement
                    runtime.tick()
                    assert COMPONENTS.get('companion.intent').prompt.text == original
                    assert load_catalog().spec('reflection') is original_flow
                assert COMPONENTS.get('companion.intent').prompt.text.endswith('Smoke version.')
                assert load_catalog().spec('reflection').edges[0].target == 'END'
                state['available'] = False
                runtime.tick()
                assert runtime.current[1].digest == replacement['digest']
                assert client.get('/health').status_code == 200
                assert state['acks']
                print('PASS: production ASGI startup, HTTP release/ack, atomic pin and live outage recovery')
            cached = release_runtime.ReleaseRuntime(os.environ['AGENT_CONFIG_SOURCE_URL'], token, cache, expected_environment='prod')
            cached.start()
            try:
                assert cached.current[1].digest == replacement['digest']
                with cached.pin():
                    assert load_catalog().spec('reflection').edges[0].target == 'END'
            finally: cached.close()
            print('PASS: cold restart with Admin unavailable uses persistent validated cache')
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
