import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { config } from '../src/lib/config';
import { hash, authorize } from '../src/lib/auth';
import { pool } from '../src/lib/db';
import { handle } from '../src/lib/api';

test('visitor permissions fail closed for mutations and permit only reads, debug and logout', () => {
  for (const [method, path] of [
    ['POST', 'drafts'],
    ['PUT', 'drafts/id'],
    ['POST', 'drafts/id/publish'],
    ['POST', 'drafts/id/discard'],
    ['POST', 'drafts/id/validate'],
    ['POST', 'releases/id/rollback'],
    ['PATCH', 'users/id'],
    ['POST', 'unknown/debug'],
  ]) {
    assert.throws(
      () => authorize({ role: 'visitor' }, method, path.split('/')),
      { status: 403 },
    );
  }
  for (const [method, path] of [
    ['GET', 'state'],
    ['POST', 'drafts/id/debug'],
    ['POST', 'releases/id/debug'],
    ['DELETE', 'session'],
  ]) {
    authorize({ role: 'visitor' }, method, path.split('/'));
  }
  assert.throws(() => authorize({ role: 'unknown' }, 'POST', ['drafts']), {
    status: 403,
  });
});

test('real database sessions enforce roles, immutable release debugging and immediate demotion', async () => {
  const previousUrl = process.env.ADMIN_DATABASE_URL;
  const url = new URL(config().databaseUrl);
  const db = new pg.Client({ connectionString: url.toString() });
  await db.connect();
  const schema = 'roles_' + randomUUID().replaceAll('-', '');
  const previousFetch = globalThis.fetch;
  try {
    await db.query(`CREATE SCHEMA "${schema}"`);
    await db.query(`SET search_path TO "${schema}"`);
    const owner = randomUUID(),
      visitor = randomUUID(),
      draft = randomUUID(),
      releasedDraft = randomUUID(),
      release = randomUUID();
    for (const file of fs
      .readdirSync('migrations')
      .filter((x) => x.endsWith('.sql'))
      .sort()) {
      if (file.startsWith('007'))
        await db.query(
          'INSERT INTO admin_users(id,email,password_hash) VALUES($1,$2,$3)',
          [owner, 'existing@example.test', 'unused'],
        );
      await db.query(fs.readFileSync('migrations/' + file, 'utf8'));
    }
    assert.equal(
      (await db.query('SELECT role FROM admin_users WHERE id=$1', [owner]))
        .rows[0].role,
      'admin',
    );
    await db.query(
      'INSERT INTO admin_users(id,email,password_hash) VALUES($1,$2,$3)',
      [visitor, 'visitor@example.test', 'unused'],
    );
    assert.equal(
      (await db.query('SELECT role FROM admin_users WHERE id=$1', [visitor]))
        .rows[0].role,
      'visitor',
    );
    await assert.rejects(
      db.query(
        "INSERT INTO admin_users(id,email,password_hash,role) VALUES($1,'invalid@example.test','unused','owner')",
        [randomUUID()],
      ),
    );
    const bundle = {
      format_version: 3,
      compatibility: 'contract',
      files: { 'agent.json': { id: 'test', prompt: { template: 'frozen' } } },
    };
    for (const [id, state] of [
      [draft, 'working'],
      [releasedDraft, 'published'],
    ])
      await db.query(
        'INSERT INTO agent_drafts(id,title,bundle,base_bundle,created_by,state) VALUES($1,$2,$3,$3,$4,$5)',
        [id, 'test', bundle, owner, state],
      );
    await db.query(
      "INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,created_by) VALUES($1,$2,1,'digest',$3,'{}',$4)",
      [release, releasedDraft, bundle, owner],
    );
    await db.query(
      "UPDATE agent_environments SET release_id=$1 WHERE name='test'",
      [release],
    );
    const tokens = { visitor: randomUUID(), admin: randomUUID() };
    for (const [role, id] of [
      ['visitor', visitor],
      ['admin', owner],
    ])
      await db.query(
        "INSERT INTO admin_sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '1 hour')",
        [hash(tokens[role as keyof typeof tokens]), id],
      );
    url.searchParams.set('options', '-csearch_path=' + schema);
    process.env.ADMIN_DATABASE_URL = url.toString();
    const requests: any[] = [];
    globalThis.fetch = async (target, init) => {
      const body = JSON.parse(String(init?.body));
      requests.push({ path: String(target), body });
      return Response.json(
        String(target).endsWith('/validate')
          ? { digest: 'digest' }
          : {
              digest: 'digest',
              status: 'succeeded',
              covered_components: ['test'],
            },
      );
    };
    const request = async (
      role: 'visitor' | 'admin',
      method: string,
      path: string,
      body?: unknown,
    ) =>
      handle(
        new Request('http://127.0.0.1:3021/api/' + path, {
          method,
          headers: {
            cookie: 'duxue_admin_session=' + tokens[role],
            origin: 'http://127.0.0.1:3021',
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        }),
        path.split('/'),
      );
    const stateResponse = await request('visitor', 'GET', 'state');
    assert.equal(stateResponse.status, 200);
    assert.equal((await stateResponse.json()).environment.name, 'test');
    const health = await request('visitor', 'GET', 'health');
    assert.equal((await health.json()).environment, 'test');
    assert.equal(
      (await (await request('visitor', 'GET', 'session')).json()).role,
      'visitor',
    );
    for (const [method, path] of [
      ['POST', 'drafts'],
      ['PUT', 'drafts/' + draft],
      ['POST', `drafts/${draft}/validate`],
      ['POST', `drafts/${draft}/discard`],
      ['POST', `drafts/${draft}/publish`],
      ['POST', `releases/${release}/rollback`],
    ])
      assert.equal(
        (await request('visitor', method, path, { revision: 1, bundle }))
          .status,
        403,
      );
    assert.equal(
      (await request('visitor', 'GET', 'drafts/' + draft)).status,
      200,
    );
    assert.equal(
      (await request('visitor', 'GET', 'releases/' + release)).status,
      200,
    );
    for (const path of [`drafts/${draft}/debug`, `releases/${release}/debug`]) {
      const result = await request('visitor', 'POST', path, {
        revision: 1,
        bundle: { injected: true },
        input: { content: 'question', component_id: 'test' },
      });
      assert.equal(result.status, 200, JSON.stringify(await result.json()));
    }
    const savedSnapshots = (
      await db.query(
        'SELECT source_kind,bundle FROM agent_debug_runs ORDER BY started_at',
      )
    ).rows;
    assert.deepEqual(
      savedSnapshots.map((row) => row.source_kind),
      ['draft', 'release'],
    );
    for (const row of savedSnapshots) assert.deepEqual(row.bundle, bundle);
    assert.equal(requests.length, 4);
    for (const item of requests) assert.deepEqual(item.body.bundle, bundle);
    assert.equal(
      (await db.query('SELECT count(*) FROM agent_drafts')).rows[0].count,
      '2',
    );
    assert.equal(
      (
        await db.query(
          "SELECT release_id FROM agent_environments WHERE name='test'",
        )
      ).rows[0].release_id,
      release,
    );
    assert.equal(
      (
        await db.query(
          'SELECT count(*) FROM agent_debug_runs WHERE created_by=$1',
          [visitor],
        )
      ).rows[0].count,
      '2',
    );
    assert.equal(
      (
        await request('admin', 'PUT', 'drafts/' + draft, {
          revision: 1,
          bundle: {
            ...bundle,
            files: {
              ...bundle.files,
              'agent.json': { id: 'test', prompt: { template: 'later edit' } },
            },
          },
        })
      ).status,
      200,
    );
    assert.deepEqual(
      (
        await db.query(
          'SELECT bundle FROM agent_debug_runs ORDER BY started_at LIMIT 1',
        )
      ).rows[0].bundle,
      bundle,
    );
    await db.query("UPDATE admin_users SET role='visitor' WHERE id=$1", [
      owner,
    ]);
    assert.equal(
      (
        await request('admin', 'PUT', 'drafts/' + draft, {
          revision: 2,
          bundle,
        })
      ).status,
      403,
    );
    await db.query('UPDATE admin_users SET active=false WHERE id=$1', [
      visitor,
    ]);
    assert.equal((await request('visitor', 'GET', 'session')).status, 401);
  } finally {
    globalThis.fetch = previousFetch;
    await pool().end();
    if (previousUrl === undefined) delete process.env.ADMIN_DATABASE_URL;
    else process.env.ADMIN_DATABASE_URL = previousUrl;
    await db.query('SET search_path TO public');
    await db.query(`DROP SCHEMA "${schema}" CASCADE`);
    await db.end();
  }
});
