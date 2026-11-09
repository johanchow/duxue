/** Real PG + private Python executor; isolated schema, no published-pointer changes. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import pg from 'pg';
import { config } from '../src/lib/config';
import { hash } from '../src/lib/auth';
import { pool } from '../src/lib/db';
import { handle } from '../src/lib/api';

const settings = config();
assert.equal(settings.environment, 'test');
const source = path.resolve(
  process.argv[2] || '../duxue-server/var/admin/release.json',
);
const schema = 'snapshot_' + randomUUID().replaceAll('-', '');
const db = new pg.Client({ connectionString: settings.databaseUrl });
const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-snapshot-'));
const url = new URL(settings.databaseUrl);
url.searchParams.set('options', '-csearch_path=' + schema);
const email = 'snapshot-test@example.test',
  actor = randomUUID(),
  token = randomUUID();
await db.connect();
try {
  await db.query(`CREATE SCHEMA "${schema}"`);
  await db.query(`SET search_path TO "${schema}"`);
  for (const file of fs
    .readdirSync('migrations')
    .filter((f) => f.endsWith('.sql'))
    .sort())
    await db.query(fs.readFileSync('migrations/' + file, 'utf8'));
  await db.query(
    "INSERT INTO admin_users(id,email,password_hash,role) VALUES($1,$2,'unused','admin')",
    [actor, email],
  );
  await db.query(
    "INSERT INTO admin_sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '1 hour')",
    [hash(token), actor],
  );
  process.env.ADMIN_DATABASE_URL = url.toString();
  const request = (name: string, method = 'GET') =>
    handle(
      new Request('http://127.0.0.1:3021/api/' + name, {
        method,
        headers: {
          cookie: 'duxue_admin_session=' + token,
          origin: 'http://127.0.0.1:3021',
        },
        body: method === 'POST' ? '{}' : undefined,
      }),
      name.split('/'),
    );
  const empty = await (await request('state')).json();
  assert.equal(empty.catalog, null);
  assert.match(empty.catalogError, /config:import/);
  assert.equal((await request('drafts', 'POST')).status, 409);
  const cli = (command: string, file: string, extra: string[] = []) =>
    spawnSync(
      process.execPath,
      ['--import', 'tsx', 'scripts/setup.ts', command, file, ...extra],
      {
        encoding: 'utf8',
        env: { ...process.env, ADMIN_INIT_EMAIL: email },
        timeout: 30000,
      },
    );
  const imported = cli('import-config', source);
  assert.equal(imported.status, 0, imported.stderr);
  const state = await (await request('state')).json();
  assert.equal(state.catalogError, null);
  assert.equal(Object.keys(state.catalog.bundle.files).length, 35);
  assert.equal(state.drafts.length, 1);
  assert.equal(state.environment.release_id, null);
  const apiExport = await request(`drafts/${state.drafts[0].id}/snapshot`);
  assert.equal(apiExport.status, 200);
  const apiSnapshot = await apiExport.json();
  assert.equal(apiSnapshot.kind, 'draft');
  assert.deepEqual(apiSnapshot.bundle, state.catalog.bundle);
  const exported = path.join(folder, 'draft.json');
  const result = cli('export-config', exported, ['--draft']);
  assert.equal(result.status, 0, result.stderr);
  const snapshot = JSON.parse(fs.readFileSync(exported, 'utf8'));
  assert.equal(snapshot.kind, 'draft');
  assert.deepEqual(snapshot.bundle, state.catalog.bundle);
  const repeated = cli('import-config', source);
  assert.notEqual(repeated.status, 0);
  assert.match(repeated.stderr, /已有草稿/);
  assert.equal(
    (await db.query('SELECT count(*) FROM agent_drafts')).rows[0].count,
    '1',
  );
  console.log(
    'PASS: empty Admin has no code defaults; real CLI import/export, full catalog and no-overwrite guards.',
  );
} finally {
  await pool().end();
  await db.query(`DROP SCHEMA "${schema}" CASCADE`);
  await db.end();
  fs.rmSync(folder, { recursive: true, force: true });
}
