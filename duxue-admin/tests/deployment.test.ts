import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
test('Docker contexts omit secrets and executor has no business DB credentials or public port', () => {
  const compose = fs.readFileSync('deploy/docker-compose.yml', 'utf8');
  assert(compose.includes('127.0.0.1:3021:3000'));
  assert(compose.includes("DATABASE_URL: 'sqlite:///:memory:'"));
  assert(compose.includes('http://executor:8011'));
  const executor = compose.split('  admin:')[0];
  assert(!executor.includes('ADMIN_DATABASE_URL'));
  assert(!executor.includes('ports:'));
  const ignore = fs.readFileSync('.dockerignore', 'utf8');
  assert(ignore.includes('.env*'));
  assert(ignore.includes('.local'));
  const nginx = fs.readFileSync('deploy/admin.nginx.conf', 'utf8');
  assert(nginx.includes('location ^~ /api/internal/ { return 404; }'));
  assert(nginx.includes('proxy_read_timeout 300s'));
});

test('local setup refuses production before any migration or database connection', () => {
  const result = spawnSync(
    process.execPath,
    ['--import', 'tsx', 'scripts/bootstrap.ts'],
    {
      encoding: 'utf8',
      env: {
        ...process.env,
        ADMIN_ENV: 'prod',
        ADMIN_DATABASE_URL:
          'postgresql://unused:unused@127.0.0.1:1/duxue-admin-prod',
        ADMIN_PUBLIC_ORIGIN: 'https://admin.duxuelai.xyz',
        AGENT_ADMIN_INTERNAL_TOKEN:
          'test-control-token-long-enough-for-bootstrap',
      },
    },
  );
  assert.notEqual(result.status, 0);
  assert(result.stderr.includes('setup仅用于本机测试环境'), result.stderr);
});
