import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { config } from '../src/lib/config';
import { passwordHash } from '../src/lib/auth';
import { serverCall } from '../src/lib/server';
import { workingDraft } from '../src/lib/working-draft';
import { transaction, pool } from '../src/lib/db';

async function main() {
  const command = process.argv[2],
    settings = config();
  if (command === 'migrate') {
    const maintenance = new URL(settings.databaseUrl);
    maintenance.pathname = '/postgres';
    const connection = new pg.Client({
      connectionString: maintenance.toString(),
    });
    await connection.connect();
    if (
      !(
        await connection.query('SELECT 1 FROM pg_database WHERE datname=$1', [
          settings.databaseName,
        ])
      ).rowCount
    )
      await connection.query(`CREATE DATABASE "${settings.databaseName}"`);
    await connection.end();
    const db = new pg.Client({ connectionString: settings.databaseUrl });
    await db.connect();
    try {
      await db.query('BEGIN');
      await db.query('SELECT pg_advisory_xact_lock(824017336)');
      await db.query(
        'CREATE TABLE IF NOT EXISTS admin_schema_migrations(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())',
      );
      for (const file of fs
        .readdirSync(path.resolve('migrations'))
        .filter((f) => f.endsWith('.sql'))
        .sort()) {
        if (
          !(
            await db.query(
              'SELECT 1 FROM admin_schema_migrations WHERE name=$1',
              [file],
            )
          ).rowCount
        ) {
          await db.query(
            fs.readFileSync(path.join('migrations', file), 'utf8'),
          );
          await db.query(
            'INSERT INTO admin_schema_migrations(name) VALUES($1)',
            [file],
          );
        }
      }
      await db.query('UPDATE agent_environments SET name=$1 WHERE name<>$1', [
        settings.environment,
      ]);
      await db.query('COMMIT');
      console.log(settings.databaseName + ' migrations applied');
    } catch (error) {
      await db.query('ROLLBACK');
      throw error;
    } finally {
      await db.end();
    }
  } else if (command === 'export-config') {
    const destination = process.argv[3];
    if (!destination) throw new Error('需要输出文件路径');
    const db = new pg.Client({ connectionString: settings.databaseUrl });
    await db.connect();
    try {
      const draft = process.argv[4] === '--draft';
      const row = draft
        ? (
            await db.query(
              "SELECT id,revision,bundle FROM agent_drafts WHERE state='working'",
            )
          ).rows[0]
        : (
            await db.query(
              'SELECT r.id,r.sequence,r.digest,r.bundle FROM agent_environments e JOIN agent_releases r ON r.id=e.release_id WHERE e.name=$1',
              [settings.environment],
            )
          ).rows[0];
      if (!row) throw new Error('没有可导出的配置');
      const validation = await serverCall('validate', { bundle: row.bundle });
      if (!draft && row.digest !== validation.digest)
        throw new Error('发布摘要不匹配');
      const snapshot = {
        ...row,
        digest: validation.digest,
        kind: draft ? 'draft' : 'release',
        environment: settings.environment,
      };
      fs.mkdirSync(path.dirname(path.resolve(destination)), {
        recursive: true,
      });
      fs.writeFileSync(destination, JSON.stringify(snapshot, null, 2) + '\n', {
        mode: 0o600,
        flag: 'wx',
      });
      console.log('Admin配置快照已导出：' + path.resolve(destination));
    } finally {
      await db.end();
    }
  } else if (command === 'import-config') {
    const source = process.argv[3];
    if (!source) throw new Error('需要Admin导出的快照路径');
    const snapshot = JSON.parse(fs.readFileSync(source, 'utf8'));
    if (!snapshot.id || !snapshot.digest || !snapshot.bundle)
      throw new Error('需要id/digest/bundle完整快照');
    const validation = await serverCall('validate', {
      bundle: snapshot.bundle,
    });
    if (validation.digest !== snapshot.digest)
      throw new Error('快照摘要不匹配');
    await transaction(async (client) => {
      const actor = (
        await client.query(
          "SELECT id FROM admin_users WHERE email=$1 AND role='admin' AND active",
          [process.env.ADMIN_INIT_EMAIL],
        )
      ).rows[0];
      if (!actor) throw new Error('ADMIN_INIT_EMAIL必须是有效管理员');
      const existing = (
        await client.query(
          'SELECT release_id FROM agent_environments WHERE name=$1',
          [settings.environment],
        )
      ).rows[0];
      if (existing.release_id)
        throw new Error('已有发布，初始化导入不会覆盖现有配置');
      const result = await workingDraft(client, {
        actorId: actor.id,
        bundle: snapshot.bundle,
        baseRelease: null,
      });
      if (!result.created) throw new Error('已有草稿，导入不会覆盖未发布修改');
    });
    console.log('配置已导入唯一草稿，需调试并发布后才生效');
  } else if (command === 'admin' || command === 'user') {
    const email = process.env.ADMIN_INIT_EMAIL?.toLowerCase(),
      password = process.env.ADMIN_INIT_PASSWORD,
      role =
        process.env.ADMIN_INIT_ROLE ||
        (command === 'admin' ? 'admin' : 'visitor');
    if (!['visitor', 'admin'].includes(role))
      throw new Error('角色必须为visitor或admin');
    if (!email || !password)
      throw new Error('请使用ADMIN_INIT_EMAIL和ADMIN_INIT_PASSWORD创建用户');
    const db = new pg.Client({ connectionString: settings.databaseUrl });
    await db.connect();
    try {
      await db.query(
        'INSERT INTO admin_users(id,email,password_hash,role) VALUES($1,$2,$3,$4)',
        [randomUUID(), email, passwordHash(password), role],
      );
      console.log(role + ' created');
    } finally {
      await db.end();
    }
  } else if (command === 'role') {
    const email = process.env.ADMIN_INIT_EMAIL?.toLowerCase(),
      role = process.env.ADMIN_INIT_ROLE;
    if (!email || !role || !['visitor', 'admin'].includes(role))
      throw new Error('需要ADMIN_INIT_EMAIL和合法ADMIN_INIT_ROLE');
    const db = new pg.Client({ connectionString: settings.databaseUrl });
    await db.connect();
    try {
      const result = await db.query(
        'UPDATE admin_users SET role=$1 WHERE email=$2 RETURNING id',
        [role, email],
      );
      if (!result.rowCount) throw new Error('用户不存在');
      console.log('user role updated');
    } finally {
      await db.end();
    }
  } else throw new Error('unknown setup command');
}
main()
  .catch((error: Error) => {
    console.error(error.message);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (process.argv[2] === 'import-config') await pool().end();
  });
