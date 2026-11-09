import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { chromium } from 'playwright';
import { pool } from '../src/lib/db';
import { passwordHash } from '../src/lib/auth';

const id = randomUUID(),
  email = `visitor-${id}@example.test`,
  password = randomUUID() + randomUUID();
const db = pool();
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
try {
  await db.query(
    'INSERT INTO admin_users(id,email,password_hash,role) VALUES($1,$2,$3,$4)',
    [id, email, passwordHash(password), 'visitor'],
  );
  const page = await browser.newPage({
    viewport: { width: 1500, height: 1100 },
  });
  page.setDefaultTimeout(20000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const origin = 'http://127.0.0.1:3021';
  await page.goto(origin);
  await page.getByLabel('管理员邮箱').fill(email);
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '登录管理台 →' }).click();
  await page.getByRole('heading', { name: 'Workflow', exact: true }).waitFor();
  const before = await (await page.request.get(origin + '/api/state')).json();
  assert.equal(before.user.role, 'visitor');
  assert(before.environment.release_id);
  await page.goto(origin + '/agents/companion.intent');
  await page.getByRole('heading', { name: '当前配置', exact: true }).waitFor();
  assert.equal(
    await page.getByRole('button', { name: '编辑配置', exact: true }).count(),
    0,
  );
  await page
    .getByRole('button', { name: '调试已发布配置', exact: true })
    .click();
  await page.getByLabel('调试输入').waitFor();
  assert.equal(await page.getByLabel('执行模型').count(), 0);
  assert.equal(await page.getByLabel('调试对象').count(), 0);
  await page.getByLabel('调试输入').fill('我有一道数学题想请你给一点提示。');
  await page.getByRole('button', { name: '运行真实调试', exact: true }).click();
  await page
    .getByRole('status')
    .filter({ hasText: '调试已记录 · 通过' })
    .waitFor({ timeout: 250000 });
  await page.screenshot({ path: '.local/visitor-debug.png', fullPage: true });
  await page.goto(origin + '/releases');
  await page.getByRole('heading', { name: '发布版本', exact: true }).waitFor();
  for (const name of [
    '放弃修改',
    '继续编辑',
    '校验配置',
    '发布到测试环境',
    '回滚到此版本',
  ])
    assert.equal(
      await page.getByRole('button', { name, exact: true }).count(),
      0,
    );
  if (before.drafts[0]) {
    await page
      .getByRole('button', { name: '查看变更与调试', exact: true })
      .click();
    await page
      .getByRole('heading', { name: '变更对照', exact: true })
      .waitFor();
    assert.equal(
      await page.getByRole('button', { name: '保存草稿', exact: true }).count(),
      0,
    );
    assert.equal(await page.getByLabel('显示名称', { exact: true }).count(), 0);
    await page
      .getByRole('button', { name: '调试已保存草稿', exact: true })
      .click();
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .waitFor();
  }
  await page.goto(origin + '/releases/' + before.environment.release_id);
  await page.getByLabel('版本详情', { exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole('button', { name: '回滚到此版本', exact: true })
      .count(),
    0,
  );
  await page.getByRole('link', { name: '下载产物' }).waitFor();
  const denied = await page.request.post(origin + '/api/drafts', {
    data: {},
    headers: { origin },
  });
  assert.equal(denied.status(), 403);
  const after = await (await page.request.get(origin + '/api/state')).json();
  assert.equal(after.environment.release_id, before.environment.release_id);
  assert.equal(after.environment.generation, before.environment.generation);
  assert.deepEqual(
    after.drafts.map((draft: any) => [draft.id, draft.revision]),
    before.drafts.map((draft: any) => [draft.id, draft.revision]),
  );
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(
    'visitor read-only UI, existing draft browsing, actual published-model debug, download and write denial: PASS',
  );
} finally {
  await browser.close();
  await db.query('DELETE FROM admin_sessions WHERE user_id=$1', [id]);
  // Keep the actor referenced by immutable debug/audit history, but disable login.
  await db.query('UPDATE admin_users SET active=false WHERE id=$1', [id]);
  await db.end();
}
