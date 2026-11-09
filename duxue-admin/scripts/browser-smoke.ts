import fs from 'node:fs';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const credentials = JSON.parse(
  fs.readFileSync('.local/bootstrap.json', 'utf8'),
);
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const page = await browser.newPage({ viewport: { width: 1450, height: 1000 } });
const errors: string[] = [];
page.on('pageerror', (e) => errors.push(e.message));
try {
  await page.goto('http://127.0.0.1:3021');
  await page.getByLabel('管理员邮箱').fill(credentials.email);
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: '登录管理台 →' }).click();
  await page.getByRole('heading', { name: 'Workflow', exact: true }).waitFor();
  const before = await (
    await page.request.get('http://127.0.0.1:3021/api/state')
  ).json();
  const rollbackSequence =
    process.env.BROWSER_ROLLBACK_SEQUENCE ||
    before.releases.find(
      (release: any) => release.id === before.environment.release_id,
    ).sequence;
  if (!process.env.BROWSER_RESUME_RELEASE) {
    await page.goto('http://127.0.0.1:3021/agents/tutoring.turn');
    await page.getByRole('button', { name: '编辑配置', exact: true }).click();
    await page.getByLabel('主Prompt', { exact: true }).waitFor();
    const prompt = page.getByLabel('主Prompt', { exact: true });
    await prompt.fill((await prompt.inputValue()) + '\n保持说明简洁清楚。');
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '草稿已保存' }).waitFor();
    await page.getByRole('button', { name: '校验配置', exact: true }).click();
    await page
      .getByRole('status')
      .filter({ hasText: '配置校验通过' })
      .waitFor();
    await page
      .getByRole('button', { name: '前往发布管理', exact: true })
      .click();
    assert(
      await page
        .getByRole('button', { name: '发布到测试环境', exact: true })
        .isDisabled(),
    );
    await page.getByRole('button', { name: '继续编辑', exact: true }).click();
    await page
      .getByRole('button', { name: '调试已保存草稿', exact: true })
      .click();
    await page
      .getByLabel('调试输入', { exact: true })
      .fill('我不知道从哪里开始，能先给我一个提示吗？');
    await page
      .getByLabel('受保护题目', { exact: true })
      .fill('小明有3盒彩笔，每盒4支，一共有多少支？');
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .click();
    await page
      .getByRole('status')
      .filter({ hasText: '调试已记录' })
      .waitFor({ timeout: 250000 });
    const message = await page
      .getByRole('status')
      .filter({ hasText: '调试已记录' })
      .innerText();
    console.log(message);
    assert(message.includes('通过'), message);
    console.log(
      'protected tutoring visible output:',
      await page.locator('.final-output').innerText(),
    );
    await page
      .getByLabel('调试对象', { exact: true })
      .selectOption('agent:tutoring.turn');
    await page
      .getByLabel('执行模型', { exact: true })
      .selectOption('tutoring.turn-backup');
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .click();
    await page
      .getByRole('status')
      .filter({ hasText: '调试已记录 · 通过' })
      .waitFor({ timeout: 250000 });
    await page.screenshot({ path: '.local/config-debug.png', fullPage: true });
    await page.getByRole('button', { name: '关闭调试', exact: true }).click();
    await page
      .getByRole('button', { name: '前往发布管理', exact: true })
      .click();
    await page
      .getByRole('button', { name: '发布到测试环境', exact: true })
      .click();
    await page.getByRole('status').filter({ hasText: '已发布' }).waitFor();
    console.log(await page.getByRole('status').innerText());
  } else {
    await page.goto(
      'http://127.0.0.1:3021/releases/' + before.environment.release_id,
    );
    await page.getByLabel('版本详情', { exact: true }).waitFor();
    await page.getByRole('status').filter({ hasText: '已发布' }).waitFor();
  }
  await page
    .locator('nav')
    .getByRole('button', { name: '发布管理', exact: false })
    .click();
  await page.locator('.load-status').evaluate((element) => {
    (element as HTMLDetailsElement).open = true;
  });
  await page
    .getByText('已加载当前发布', { exact: true })
    .waitFor({ timeout: 65000 });
  console.log('new release acknowledged in UI');
  await page
    .locator('nav')
    .getByRole('button', { name: '发布管理', exact: false })
    .click();
  await page
    .locator('tbody tr')
    .filter({ has: page.getByText(`R${rollbackSequence}`, { exact: true }) })
    .getByRole('button', { name: '回滚到此版本' })
    .click();
  await page
    .getByRole('status')
    .filter({ hasText: `已切换至R${rollbackSequence}` })
    .waitFor();
  await page
    .locator('nav')
    .getByRole('button', { name: '发布管理', exact: false })
    .click();
  await page.locator('.load-status').evaluate((element) => {
    (element as HTMLDetailsElement).open = true;
  });
  await page
    .getByText('已加载当前发布', { exact: true })
    .waitFor({ timeout: 65000 });
  await page.screenshot({ path: '.local/overview-final.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '.local/mobile.png', fullPage: true });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    'mobile horizontal overflow',
  );
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(
    'edit, validate, publish guard, real protected debug, publish, ack, rollback, desktop/mobile: PASS',
  );
} finally {
  await browser.close();
}
