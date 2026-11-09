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
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
page.setDefaultTimeout(20000);
const errors: string[] = [];
page.on('pageerror', (e) => errors.push(e.message));
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
  const run = async () => {
    const response = page.waitForResponse(
      (response) =>
        response.url().endsWith('/debug') &&
        response.request().method() === 'POST',
      { timeout: 250000 },
    );
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .click();
    const http = await response;
    const result = await http.json();
    assert.equal(http.status(), 200, JSON.stringify(result));
    assert.equal(result.status, 'succeeded', JSON.stringify(result));
    await page
      .getByRole('status')
      .filter({ hasText: '调试已记录 · 通过' })
      .waitFor();
    return result;
  };
  await page.goto(origin + '/agents/companion.intent');
  await page
    .getByRole('button', { name: '调试已发布配置', exact: true })
    .click();
  await page
    .getByLabel('调试输入', { exact: true })
    .fill('我有一道数学题想请你给一点提示。');
  assert.equal(await page.getByLabel('调试对象', { exact: true }).count(), 0);
  assert.equal(await page.getByLabel('执行模型', { exact: true }).count(), 0);
  const agent = await run();
  assert.equal(agent.source.kind, 'release');
  assert.equal(agent.target.id, 'companion.intent');
  assert.deepEqual(agent.covered_components, ['companion.intent']);
  assert.equal(agent.steps.length, 1);
  await page.goto(origin + `/agents/tutoring.turn?draft=${draft.id}`);
  const prompt = page.getByLabel('主Prompt', { exact: true });
  await prompt.waitFor();
  await prompt.fill((await prompt.inputValue()) + '\n仅用于未保存拦截测试。');
  await page
    .getByRole('button', { name: '调试已保存草稿', exact: true })
    .click();
  assert.deepEqual(
    await page
      .getByLabel('执行模型')
      .locator('option')
      .evaluateAll((options) =>
        options.map((o) => (o as HTMLOptionElement).value),
      ),
    ['tutoring.turn', 'tutoring.turn-backup'],
  );
  assert(
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .isDisabled(),
  );
  await page.reload();
  await prompt.waitFor();
  assert(!(await prompt.inputValue()).includes('仅用于未保存拦截测试。'));
  await page.goto(origin + '/workflows/review-aspects');
  await page
    .getByRole('button', { name: '调试已发布配置', exact: true })
    .click();
  await page
    .getByLabel('调试输入', { exact: true })
    .fill('今天我学会了用画图的方法理解乘法。');
  const flow = await run();
  assert.equal(flow.source.kind, 'release');
  assert.equal(flow.target.id, 'review-aspects');
  assert(
    flow.events.some((event: any) => event.kind === 'edge' && event.selected),
  );
  await page.getByRole('button', { name: '查看流程执行', exact: true }).click();
  await page.locator('.react-flow__node[data-id="review-aspects.run"]').click();
  await page.getByLabel('选中对象执行数据').waitFor();
  assert(
    (await page.getByLabel('选中对象执行数据').innerText()).includes('aspects'),
  );
  await page.screenshot({
    path: '.local/workflow-debug-nodes.png',
    fullPage: true,
  });
  await page.goto(origin + `/workflows/reflection?draft=${draft.id}`);
  await page
    .getByRole('button', { name: '调试已保存草稿', exact: true })
    .click();
  await page.getByLabel('调试输入', { exact: true }).waitFor();
  const saved = await run();
  assert.equal(saved.source.kind, 'draft');
  assert.equal(saved.source.revision, draft.revision);
  assert.equal(saved.model_requests, 0);
  await page.goto(origin + '/workflows/tutoring');
  await page
    .getByRole('button', { name: '调试已发布配置', exact: true })
    .click();
  await page
    .getByLabel('调试输入', { exact: true })
    .fill('我不知道从哪里开始，能先给一个提示吗？');
  await page
    .getByLabel('受保护题目', { exact: true })
    .fill('小明有3盒彩笔，每盒4支，一共有多少支？');
  const tutor = await run();
  assert.equal(tutor.target.id, 'tutoring');
  assert(
    tutor.events.some(
      (event: any) => event.node_id === 'tutoring.output_safety',
    ),
  );
  assert(tutor.covered_components.includes('tutoring.leak-judge'));
  await page.getByRole('button', { name: '查看流程执行', exact: true }).click();
  await page.locator('.react-flow__node[data-id="tutoring.attempt"]').click();
  await page.getByLabel('选中对象执行数据').waitFor();
  await page.screenshot({
    path: '.local/tutoring-debug-nodes.png',
    fullPage: true,
  });
  await page.goto(origin + '/agents/tutoring.tool_budget');
  await page.getByText('未开放独立调试', { exact: true }).waitFor();
  assert.equal(
    await page
      .getByRole('button', { name: '运行真实调试', exact: true })
      .count(),
    0,
  );
  const after = await (await page.request.get(origin + '/api/state')).json();
  assert.equal(after.environment.release_id, before.environment.release_id);
  assert.equal(after.drafts[0].revision, before.drafts[0].revision);
  assert.equal(errors.length, 0, errors.join('\n'));
  fs.writeFileSync(
    '.local/debugging-verification.json',
    JSON.stringify(
      {
        agent: agent.id,
        flow: flow.id,
        draft: saved.id,
        tutoring: tutor.id,
        release: before.environment.release_id,
      },
      null,
      2,
    ),
  );
  console.log(
    'locked Agent targets, published/draft snapshot sources, unsaved guard, real workflows, node/edge inspection and unsupported component handling: PASS',
  );
} finally {
  await browser.close();
}
