import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromium } from 'playwright';
const origin = 'http://127.0.0.1:3021';
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
page.setDefaultTimeout(20000);
const errors: string[] = [];
page.on('pageerror', (error) => errors.push(error.message));
try {
  const credentials = JSON.parse(
    fs.readFileSync('.local/bootstrap.json', 'utf8'),
  );
  await page.goto(origin);
  await page.getByLabel('管理员邮箱').fill(credentials.email);
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: '登录管理台 →' }).click();
  await page.getByRole('heading', { name: 'Workflow', exact: true }).waitFor();
  const before = await (await page.request.get(origin + '/api/state')).json();
  const draft = before.drafts[0];
  assert(draft);
  const drawer = page.getByRole('dialog', { name: '调试面板', exact: true });
  const close = async () => {
    await page.getByRole('button', { name: '关闭调试', exact: true }).click();
    await drawer.waitFor({ state: 'hidden' });
  };
  await page.goto(origin + '/agents/companion.intent');
  const trigger = page.getByRole('button', {
    name: '调试已发布配置',
    exact: true,
  });
  await trigger.click();
  await drawer.waitFor();
  const input = drawer.getByLabel('调试输入', { exact: true });
  await input.waitFor();
  await input.fill('保留我的调试输入');
  assert(await input.evaluate((el) => document.activeElement === el));
  const bounds = await input.boundingBox();
  assert(bounds && bounds.y >= 0 && bounds.y + bounds.height <= 1000);
  assert.equal(
    await page.evaluate(() => document.body.style.overflow),
    'hidden',
  );
  await page.screenshot({
    path: '.local/debug-drawer-agent.png',
    fullPage: false,
  });
  await close();
  assert(await trigger.evaluate((el) => document.activeElement === el));
  assert.equal(await page.evaluate(() => document.body.style.overflow), '');
  await trigger.click();
  assert.equal(await input.inputValue(), '保留我的调试输入');
  await page.keyboard.press('Escape');
  await drawer.waitFor({ state: 'hidden' });
  await page.goto(origin + `/agents/tutoring.turn?draft=${draft.id}`);
  await page.getByLabel('主Prompt', { exact: true }).waitFor();
  const prompt = page.getByLabel('主Prompt', { exact: true });
  await prompt.fill((await prompt.inputValue()) + '\n未保存测试');
  await page
    .getByRole('button', { name: '调试已保存草稿', exact: true })
    .click();
  await drawer.waitFor();
  assert(
    await drawer
      .getByRole('button', { name: '运行真实调试', exact: true })
      .isDisabled(),
  );
  await close();
  await page.reload();
  await prompt.waitFor();
  await page.goto(origin + '/workflows/reflection');
  await page
    .getByRole('button', { name: '调试已保存草稿', exact: true })
    .click();
  await drawer.waitFor();
  await drawer.getByLabel('调试输入', { exact: true }).waitFor();
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/debug') && r.request().method() === 'POST',
    { timeout: 250000 },
  );
  await drawer
    .getByRole('button', { name: '运行真实调试', exact: true })
    .click();
  const result = await (await response).json();
  assert.equal(result.status, 'succeeded', JSON.stringify(result));
  assert.equal(result.model_requests, 0);
  await drawer
    .getByRole('button', { name: '查看流程执行', exact: true })
    .click();
  await drawer.waitFor({ state: 'hidden' });
  await page.locator('.react-flow__node[data-id="reflection.turn"]').click();
  await page.getByLabel('选中对象执行数据').waitFor();
  await page
    .getByRole('button', { name: '调试已保存草稿', exact: true })
    .click();
  await drawer.waitFor();
  await drawer
    .getByRole('heading', { name: 'Workflow 执行输出', exact: true })
    .waitFor();
  await close();
  await page.goto(origin + '/agents/tutoring.tool_budget');
  await page.getByText('未开放独立调试', { exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole('button', { name: '调试已发布配置', exact: true })
      .count(),
    0,
  );
  await page
    .getByRole('button', { name: '打开所属 Workflow', exact: true })
    .click();
  await page.waitForURL('**/workflows/tutoring');
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('button', { name: '调试已发布配置', exact: true })
    .click();
  await drawer.waitFor();
  await drawer.getByLabel('调试输入', { exact: true }).waitFor();
  const mobile = await drawer.boundingBox();
  assert(mobile && mobile.width <= 390 && mobile.x >= 0);
  assert.equal(
    await drawer.evaluate((el) => el.scrollWidth <= el.clientWidth),
    true,
  );
  await page.screenshot({
    path: '.local/debug-drawer-mobile.png',
    fullPage: false,
  });
  await close();
  const after = await (await page.request.get(origin + '/api/state')).json();
  assert.equal(after.environment.release_id, before.environment.release_id);
  assert.equal(after.drafts[0].revision, before.drafts[0].revision);
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(
    'drawer immediate input, focus/scroll isolation, close/reopen retention, unsaved guard, Workflow inspection, specific capability guidance and mobile: PASS',
  );
} finally {
  await browser.close();
}
