import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

function fixture(
  run: (root: string, load: () => ReturnType<typeof spawnSync>) => void,
) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-config-'));
  const root = path.join(base, 'duxue-admin');
  fs.mkdirSync(root);
  fs.mkdirSync(path.join(base, 'duxue-server'));
  const env: NodeJS.ProcessEnv = { ...process.env, ADMIN_ROOT: root };
  for (const key of Object.keys(env)) {
    if (
      (key.startsWith('ADMIN_') && key !== 'ADMIN_ROOT') ||
      key.startsWith('AGENT_')
    )
      delete env[key];
  }
  const configUrl = pathToFileURL(path.resolve('src/lib/config.ts')).href;
  const load = () =>
    spawnSync(
      process.execPath,
      [
        '--import',
        'tsx',
        '--input-type=module',
        '--eval',
        `import { config } from ${JSON.stringify(configUrl)}; console.log(JSON.stringify(config()));`,
      ],
      { env, encoding: 'utf8' },
    );
  try {
    run(root, load);
  } finally {
    fs.rmSync(base, { recursive: true, force: true });
  }
}

const token = 'configuration-test-token-long-enough-for-testing';
const contents = `ADMIN_ENV=test\nADMIN_DATABASE_URL=postgresql://test:unused@configured-host:5432/duxue-admin-test\nAGENT_ADMIN_INTERNAL_TOKEN=${token}\n`;

test('local config reads explicit database and shared token from .env only', () => {
  fixture((root, load) => {
    fs.writeFileSync(path.join(root, '.env'), contents);
    fs.writeFileSync(
      path.join(root, '.env.local'),
      'ADMIN_DATABASE_URL=postgresql://wrong:wrong@wrong-host/wrong\n',
    );
    fs.writeFileSync(
      path.join(root, '.env.example'),
      'ADMIN_DATABASE_URL=postgresql://wrong:wrong@example-host/wrong\n',
    );
    const r = load();
    assert.equal(r.status, 0, String(r.stderr));
    const settings = JSON.parse(String(r.stdout));
    assert.equal(new URL(settings.databaseUrl).hostname, 'configured-host');
    assert.equal(new URL(settings.databaseUrl).pathname, '/duxue-admin-test');
    assert.equal(settings.token, token);
  });
});

test('missing explicit database is an error even when sibling Server and legacy files contain it', () => {
  fixture((root, load) => {
    fs.writeFileSync(
      path.join(root, '.env'),
      `AGENT_ADMIN_INTERNAL_TOKEN=${token}\n`,
    );
    fs.writeFileSync(
      path.join(root, '../duxue-server/.env'),
      'DATABASE_URL=postgresql://wrong:wrong@server-host/duxue-test\n',
    );
    fs.writeFileSync(path.join(root, '.env.local'), contents);
    fs.writeFileSync(path.join(root, '.env.example'), contents);
    const r = load();
    assert.notEqual(r.status, 0);
    assert(String(r.stderr).includes('ADMIN_DATABASE_URL'), String(r.stderr));
  });
});
