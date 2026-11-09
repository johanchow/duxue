import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { config } from '../src/lib/config';
import { passwordHash } from '../src/lib/auth';

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
main().catch((error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
