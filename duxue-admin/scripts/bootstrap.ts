import fs from 'node:fs';
import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import pg from 'pg';
const { config } = await import('../src/lib/config');
if (config().environment !== 'test')
  throw new Error(
    'npm run setup仅用于本机测试环境；正式环境使用镜像迁移与独立账号初始化命令',
  );
fs.mkdirSync('.local', { recursive: true, mode: 0o700 });
if (!fs.existsSync('.local/bootstrap.json'))
  fs.writeFileSync(
    '.local/bootstrap.json',
    JSON.stringify(
      {
        email: process.env.ADMIN_INIT_EMAIL || 'admin@duxue.local',
        password:
          process.env.ADMIN_INIT_PASSWORD ||
          randomBytes(24).toString('base64url'),
      },
      null,
      2,
    ),
    { mode: 0o600 },
  );
function run(command: string, extra: Record<string, string> = {}) {
  const result = spawnSync(
    process.execPath,
    ['--import', 'tsx', 'scripts/setup.ts', command],
    { env: { ...process.env, ...extra }, stdio: 'inherit' },
  );
  if (result.status !== 0) process.exit(result.status || 1);
}
run('migrate');

const credentials = JSON.parse(
  fs.readFileSync('.local/bootstrap.json', 'utf8'),
);
const db = new pg.Client({ connectionString: config().databaseUrl });
await db.connect();
const user = (
  await db.query('SELECT password_hash FROM admin_users WHERE email=$1', [
    credentials.email,
  ])
).rows[0];
await db.end();
if (user) {
  const { checkPassword } = await import('../src/lib/auth');
  if (!checkPassword(credentials.password, user.password_hash))
    throw new Error('本地初始化凭据与已有管理员不匹配，初始化不会重置密码。');
}
if (!user)
  run('admin', {
    ADMIN_INIT_EMAIL: credentials.email,
    ADMIN_INIT_PASSWORD: credentials.password,
    ADMIN_INIT_ROLE: 'admin',
  });
console.log(
  'Setup complete. Local credentials: .local/bootstrap.json (not committed).',
);
