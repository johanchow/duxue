import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { config } from '../src/lib/config';
import { workingDraft } from '../src/lib/working-draft';
test('PostgreSQL migration enforces immutable releases, references, optimistic revisions and test-only environments', async () => {
  const db = new pg.Client({ connectionString: config().databaseUrl });
  await db.connect();
  try {
    await db.query('BEGIN');
    const schema = 'test_admin_' + randomUUID().replaceAll('-', '');
    await db.query(`CREATE SCHEMA "${schema}"`);
    await db.query(`SET LOCAL search_path TO "${schema}"`);
    for (const file of fs
      .readdirSync('migrations')
      .filter((x) => x.endsWith('.sql'))
      .sort())
      await db.query(fs.readFileSync('migrations/' + file, 'utf8'));
    const user = randomUUID(),
      draft = randomUUID(),
      run = randomUUID(),
      release = randomUUID();
    await db.query(
      'INSERT INTO admin_users(id,email,password_hash) VALUES($1,$2,$3)',
      [user, 'schema-test@example.test', 'unused'],
    );
    await db.query(
      'INSERT INTO agent_drafts(id,title,bundle,created_by) VALUES($1,$2,$3,$4)',
      [draft, 'schema test', {}, user],
    );
    const update = await db.query(
      'UPDATE agent_drafts SET revision=revision+1 WHERE id=$1 AND revision=1 RETURNING revision',
      [draft],
    );
    assert.equal(update.rows[0].revision, 2);
    assert.equal(
      (
        await db.query(
          'UPDATE agent_drafts SET revision=revision+1 WHERE id=$1 AND revision=1 RETURNING revision',
          [draft],
        )
      ).rowCount,
      0,
    );
    const first = await workingDraft(db, {
      actorId: user,
      bundle: { files: {} },
      baseRelease: null,
    });
    const repeated = await workingDraft(db, {
      actorId: user,
      bundle: { files: { ignored: true } },
      baseRelease: null,
    });
    assert.equal(first.created, true);
    assert.equal(repeated.created, false);
    assert.equal(first.draft.id, repeated.draft.id);
    assert.deepEqual(repeated.draft.bundle, first.draft.bundle);
    await db.query('SAVEPOINT only_one_draft');
    await assert.rejects(
      db.query(
        "INSERT INTO agent_drafts(id,title,bundle,created_by,state) VALUES($1,'second','{}',$2,'working')",
        [randomUUID(), user],
      ),
    );
    await db.query('ROLLBACK TO SAVEPOINT only_one_draft');
    await db.query("UPDATE agent_drafts SET state='published' WHERE id=$1", [
      first.draft.id,
    ]);
    const next = await workingDraft(db, {
      actorId: user,
      bundle: { files: {} },
      baseRelease: null,
    });
    assert.notEqual(next.draft.id, first.draft.id);
    assert.equal(
      (
        await db.query(
          "SELECT count(*) FROM agent_drafts WHERE state='working'",
        )
      ).rows[0].count,
      '1',
    );
    await db.query(
      "INSERT INTO agent_debug_runs(id,draft_id,revision,digest,input,status,created_by) VALUES($1,$2,2,'digest','{}','succeeded',$3)",
      [run, draft, user],
    );
    await db.query(
      "INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,debug_run_id,created_by) VALUES($1,$2,2,'digest','{}','{}',$3,$4)",
      [release, draft, run, user],
    );
    for (const sql of [
      "UPDATE agent_releases SET digest='changed'",
      'DELETE FROM agent_releases',
      "INSERT INTO agent_environments(name) VALUES('production')",
    ]) {
      await db.query('SAVEPOINT rejected');
      await assert.rejects(db.query(sql));
      await db.query('ROLLBACK TO SAVEPOINT rejected');
    }
    assert.equal(
      (await db.query('SELECT digest FROM agent_releases')).rows[0].digest,
      'digest',
    );
    await db.query('SAVEPOINT evidence');
    await assert.rejects(
      db.query(
        "INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,debug_run_id,created_by) VALUES($1,$2,3,'other-digest','{}','{}',$3,$4)",
        [randomUUID(), draft, run, user],
      ),
    );
    await db.query('ROLLBACK TO SAVEPOINT evidence');
    await db.query(
      "INSERT INTO agent_debug_runs(id,draft_id,revision,digest,input,status,created_by) VALUES($1,$2,2,'digest','{}','running',$3)",
      [randomUUID(), draft, user],
    );
    await db.query('SAVEPOINT single_flight');
    await assert.rejects(
      db.query(
        "INSERT INTO agent_debug_runs(id,draft_id,revision,digest,input,status,created_by) VALUES($1,$2,2,'digest','{}','running',$3)",
        [randomUUID(), draft, user],
      ),
    );
    await db.query('ROLLBACK TO SAVEPOINT single_flight');
    const metadataRelease = randomUUID();
    await db.query(
      "INSERT INTO agent_releases(id,draft_id,revision,digest,bundle,validation,debug_run_id,created_by) VALUES($1,$2,3,'metadata-only','{}','{}',NULL,$3)",
      [metadataRelease, draft, user],
    );
    assert.equal(
      (
        await db.query('SELECT debug_run_id FROM agent_releases WHERE id=$1', [
          metadataRelease,
        ])
      ).rows[0].debug_run_id,
      null,
    );
  } finally {
    await db.query('ROLLBACK');
    await db.end();
  }
});
