import {
  createHash,
  randomBytes,
  scryptSync,
  timingSafeEqual,
} from 'node:crypto';
import { pool, transaction, audit } from './db';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export const hash = (value: string) =>
  createHash('sha256').update(value).digest('hex');
export function passwordHash(password: string) {
  if (password.length < 14) throw new Error('密码至少14位');
  const salt = randomBytes(16).toString('hex');
  return salt + ':' + scryptSync(password, salt, 64).toString('hex');
}
export function checkPassword(password: string, stored: string) {
  const [salt, value] = stored.split(':');
  if (!salt || !value || value.length !== 128) return false;
  return timingSafeEqual(
    scryptSync(password, salt, 64),
    Buffer.from(value, 'hex'),
  );
}
export function checkOrigin(request: Request) {
  const url = new URL(request.url);
  const expected =
    process.env.ADMIN_PUBLIC_ORIGIN ||
    (request.headers.get('host')
      ? url.protocol + '//' + request.headers.get('host')
      : url.origin);
  if (request.headers.get('origin') !== expected)
    throw new ApiError(403, '请求来源不匹配');
}
export function sessionToken(request: Request) {
  return request.headers
    .get('cookie')
    ?.split(';')
    .map((x) => x.trim())
    .find((x) => x.startsWith('duxue_admin_session='))
    ?.split('=')[1];
}
export async function requireUser(request: Request) {
  const token = sessionToken(request);
  if (!token) throw new ApiError(401, '请先登录');
  const result = await pool().query(
    'SELECT u.id,u.email,u.role FROM admin_sessions s JOIN admin_users u ON u.id=s.user_id WHERE s.token_hash=$1 AND s.expires_at>now() AND u.active',
    [hash(token)],
  );
  if (!result.rows[0]) throw new ApiError(401, '登录已过期');
  return result.rows[0] as {
    id: string;
    email: string;
    role: 'visitor' | 'admin';
  };
}
export async function login(email: string, password: string) {
  const key = hash(email.toLowerCase());
  return transaction(async (client) => {
    await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [key]);
    const attempts = await client.query(
      "SELECT count(*) FROM admin_login_attempts WHERE key_hash=$1 AND created_at>now()-interval '15 minutes'",
      [key],
    );
    if (Number(attempts.rows[0].count) >= 10)
      throw new ApiError(429, '尝试过多，请15分钟后重试');
    await client.query(
      'INSERT INTO admin_login_attempts(key_hash) VALUES($1)',
      [key],
    );
    const result = await client.query(
      'SELECT * FROM admin_users WHERE email=$1 AND active',
      [email.toLowerCase()],
    );
    const user = result.rows[0];
    if (
      !checkPassword(
        password,
        user?.password_hash || '0'.repeat(32) + ':' + '0'.repeat(128),
      )
    )
      return null;
    const token = randomBytes(32).toString('hex');
    await client.query(
      "INSERT INTO admin_sessions(token_hash,user_id,expires_at) VALUES($1,$2,now()+interval '12 hours')",
      [hash(token), user.id],
    );
    await audit(client, user.id, 'login', null);
    return token;
  });
}

/** Fail closed for every write route except explicit debugging and logout. */
export function authorize(
  user: { role: string },
  method: string,
  parts: string[],
) {
  if (method === 'GET' || user.role === 'admin') return;
  if (method === 'DELETE' && parts.join('/') === 'session') return;
  if (
    method === 'POST' &&
    parts.length === 3 &&
    ['drafts', 'releases'].includes(parts[0]) &&
    parts[2] === 'debug'
  )
    return;
  throw new ApiError(403, 'visitor只能查看和调试，不能修改配置、发布或回滚');
}
