import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { config } from '../src/lib/config';
import { hash } from '../src/lib/auth';
import { pool } from '../src/lib/db';
import { handle } from '../src/lib/api';
import { studioRoute } from '../src/lib/studio-route';

test('evaluation native routes reject retired detail routes', () => {
  for (const page of ['overview', 'experiments', 'production'])
    assert.equal(studioRoute(`/evals/${page}`).tab, 'evaluation');
  assert.equal(studioRoute('/evals/old-run-id').tab, 'missing');
});
test('authenticated read aggregation, exact release/draft association and retired storage absent', async () => {
  const previous = { ...process.env },
    previousFetch = globalThis.fetch;
  const url = new URL(config().databaseUrl),
    db = new pg.Client({ connectionString: url.toString() }),
    schema = 'evaluation_' + randomUUID().replaceAll('-', '');
  await db.connect();
  try {
    await db.query(`CREATE SCHEMA "${schema}"`);
    await db.query(`SET search_path TO "${schema}"`);
    for (const file of fs
      .readdirSync('migrations')
      .filter((f) => f.endsWith('.sql'))
      .sort())
      await db.query(fs.readFileSync('migrations/' + file, 'utf8'));
    assert.equal(
      (
        await db.query(
          "SELECT count(*)::int n FROM information_schema.tables WHERE table_schema=$1 AND table_name IN ('eval_runs','eval_reviews')",
          [schema],
        )
      ).rows[0].n,
      0,
    );
    const user = randomUUID(),
      draft = randomUUID(),
      release = randomUUID(),
      token = randomUUID(),
      digest = 'a'.repeat(64);
    await db.query(
      "INSERT INTO admin_users(id,email,password_hash,role) VALUES($1,'eval@example.test','unused','visitor')",
      [user],
    );
    await db.query(
      "INSERT INTO admin_sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '1 hour')",
      [hash(token), user],
    );
    await db.query(
      "INSERT INTO agent_drafts(id,title,bundle,base_bundle,created_by,validation,state) VALUES($1,'candidate','{}','{}',$2,$3,'working')",
      [draft, user, { digest }],
    );
    await db.query(
      "INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,created_by) VALUES($1,$2,1,$3,'{}','{}',$4)",
      [release, draft, digest, user],
    );
    url.searchParams.set('options', '-csearch_path=' + schema);
    process.env.ADMIN_DATABASE_URL = url.toString();
    Object.assign(process.env, {
      ADMIN_LANGFUSE_BASE_URL: 'https://lf.example',
      ADMIN_LANGFUSE_PROJECT_ID: 'p',
      ADMIN_LANGFUSE_PUBLIC_KEY: 'pk',
      ADMIN_LANGFUSE_SECRET_KEY: 'private-test-key',
      ADMIN_LANGFUSE_ENVIRONMENT: 'production',
    });
    globalThis.fetch = async (target) => {
      const q = new URL(String(target)).searchParams.get('query');
      if (
        q &&
        new Date(JSON.parse(q).toTimestamp).getTime() <
          Date.now() - 20 * 86400000
      )
        return Response.json({ error: 'history unavailable' }, { status: 400 });
      return Response.json(
        String(target).endsWith('/projects')
          ? { data: [{ id: 'p' }] }
          : String(target).includes('/experiments?')
            ? {
                data: [
                  {
                    id: 'e1',
                    name: 'candidate',
                    itemCount: 2,
                    metadata: { config_digest: digest },
                  },
                  {
                    id: 'e2',
                    name: 'unmatched',
                    metadata: { config_digest: 'b'.repeat(64) },
                  },
                ],
                meta: { cursor: 'next' },
              }
            : { data: [] },
      );
    };
    const request = (method: string, path: string, authenticated = true) =>
      handle(
        new Request('http://127.0.0.1:3021/api/' + path, {
          method,
          headers: {
            origin: 'http://127.0.0.1:3021',
            ...(authenticated
              ? { cookie: 'duxue_admin_session=' + token }
              : {}),
          },
        }),
        path.split('?')[0].split('/'),
      );
    assert.equal(
      (await request('GET', 'evaluation/experiments', false)).status,
      401,
    );
    const response = await request('GET', 'evaluation/experiments');
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.experiments[0].releases[0].id, release);
    assert.equal(data.experiments[0].drafts[0].id, draft);
    assert.equal(data.experiments[1].releases.length, 0);
    assert.equal(data.cursor, 'next');
    assert.equal(Object.hasOwn(data.links, 'Test Cases'), false);
    const production = await request('GET', 'evaluation/production?days=30');
    assert.equal(production.status, 200);
    const summary = await production.json();
    assert.equal(summary.current.taskCount, 0);
    assert.equal(summary.baseline, null);
    assert.match(summary.warning, /基线不可用/);
    assert.ok(!JSON.stringify(data).includes('private-test-key'));
    assert.equal(
      (await request('GET', 'evaluation/overview?current=missing')).status,
      400,
    );
    assert.equal(
      (await request('GET', 'evaluation/production?days=999')).status,
      400,
    );
    assert.equal((await request('POST', 'evaluation/experiments')).status, 403);
    assert.equal((await request('GET', 'evals')).status, 404);
    await db.query("UPDATE admin_users SET role='admin' WHERE id=$1", [user]);
    assert.equal((await request('POST', 'evaluation/experiments')).status, 405);
    assert.equal((await request('POST', 'evals')).status, 404);
  } finally {
    globalThis.fetch = previousFetch;
    await pool().end();
    delete (globalThis as any).adminPool;
    for (const key of Object.keys(process.env))
      if (!(key in previous)) delete process.env[key];
    Object.assign(process.env, previous);
    await db.query('SET search_path TO public');
    await db.query(`DROP SCHEMA "${schema}" CASCADE`);
    await db.end();
  }
});
