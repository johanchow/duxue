import pg, { type PoolClient } from 'pg';
import { config } from './config';
const globalDb = globalThis as unknown as { adminPool?: pg.Pool };
export function pool() {
  return (globalDb.adminPool ||= new pg.Pool({
    connectionString: config().databaseUrl,
    max: 8,
    connectionTimeoutMillis: 10000,
    idleTimeoutMillis: 30000,
  }));
}
export async function transaction<T>(work: (client: PoolClient) => Promise<T>) {
  const client = await pool().connect();
  try {
    await client.query('BEGIN');
    const value = await work(client);
    await client.query('COMMIT');
    return value;
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
export async function audit(
  client: Pick<PoolClient, 'query'>,
  actor: string,
  action: string,
  target: string | null,
  details: unknown = {},
) {
  await client.query(
    'INSERT INTO admin_audit(actor_id,action,target_id,details) VALUES($1,$2,$3,$4)',
    [actor, action, target, JSON.stringify(details)],
  );
}
