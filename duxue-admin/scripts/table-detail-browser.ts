import fs from 'node:fs';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
const origin = 'http://127.0.0.1:3021';
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
page.setDefaultTimeout(15000);
const errors: string[] = [];
page.on('pageerror', (error) => errors.push(error.message));
try {
  await page.goto(origin);
  const credentials = JSON.parse(
    fs.readFileSync('.local/bootstrap.json', 'utf8'),
  );
  await page.getByLabel('管理员邮箱').fill(credentials.email);
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: '登录管理台 →' }).click();
  await page.getByRole('heading', { name: 'Workflow', exact: true }).waitFor();
  const state = await (await page.request.get(origin + '/api/state')).json();
  const nav = page.locator('nav');
  assert.equal(
    await nav.getByRole('button', { name: '配置工作台', exact: false }).count(),
    0,
  );
  const menu = await nav.innerText();
  assert(menu.indexOf('Workflow') < menu.indexOf('Agent'));
  assert(!menu.includes('配置草稿'));
  assert(!menu.includes('工作概览'));
  assert(!menu.includes('操作审计'));
  await nav.getByRole('button', { name: 'Workflow', exact: false }).click();
  await page.waitForURL('**/workflows');
  const workflowTable = page.getByRole('table', {
    name: 'Workflow 列表',
    exact: true,
  });
  await workflowTable.waitFor();
  assert.equal(
    await workflowTable.locator('tbody tr').count(),
    state.catalog.counts.workflows,
  );
  const headers = await workflowTable.locator('th').allTextContents();
  assert.deepEqual(headers, ['Workflow', '简介', '配置']);
  await page.screenshot({ path: '.local/workflow-table.png', fullPage: true });
  for (const [id, flow] of Object.entries(state.catalog.workflows) as [
    string,
    any,
  ][]) {
    await page.goto(origin + '/workflows/' + id);
    await page
      .getByRole('button', { name: '返回 Workflow 列表', exact: false })
      .waitFor();
    await page.waitForFunction(
      (count) =>
        document.querySelectorAll('.react-flow__node').length === count,
      flow.nodes.length + 2,
      { timeout: 15000 },
    );
    await page.waitForFunction(
      (count) =>
        document.querySelectorAll('.react-flow__edge:not([data-id^="parent-"])')
          .length === count,
      flow.edges.length,
      { timeout: 15000 },
    );
  }
  await page.goto(origin + '/workflows/tutoring-vet');
  await page
    .locator('.react-flow__node[data-id="tutoring-vet.text_leak"]')
    .click();
  assert(
    (await page.getByTestId('selection-config').innerText()).includes(
      'tutoring.leak-judge',
    ),
  );
  await page
    .locator(
      '.react-flow__edge[data-id="edge-1"] .react-flow__edge-textwrapper',
    )
    .click();
  assert(
    (await page.getByTestId('selection-config').innerText()).includes(
      'authority_denied',
    ),
  );
  await page.getByRole('button', { name: '查看完整 Workflow 配置' }).click();
  assert.deepEqual(
    JSON.parse(
      await page.getByLabel('Workflow 完整配置').locator('pre').innerText(),
    ),
    state.catalog.workflows['tutoring-vet'],
  );
  await page.screenshot({ path: '.local/workflow-detail.png', fullPage: true });
  await page.reload();
  await page
    .getByRole('button', { name: '返回 Workflow 列表', exact: false })
    .click();
  await page.waitForURL('**/workflows');
  await nav.getByRole('button', { name: 'Agent', exact: false }).click();
  await page.waitForURL('**/agents');
  const agentTable = page.getByRole('table', {
    name: 'Agent 列表',
    exact: true,
  });
  await agentTable.waitFor();
  assert(!(await agentTable.locator('th').allTextContents()).includes('版本'));
  for (const id of state.drafts[0]?.changed_ids || []) {
    const row = agentTable
      .locator('tbody tr')
      .filter({ has: page.getByText(id, { exact: true }) });
    if (await row.count())
      assert((await row.innerText()).includes('有待发布修改'));
  }

  assert.equal(
    await agentTable.locator('tbody tr').count(),
    state.catalog.counts.components,
  );
  await page.screenshot({ path: '.local/agent-table.png', fullPage: true });
  for (const type of [
    'model-agent',
    'code-agent',
    'model-judge',
    'code-gate',
    'tool',
  ]) {
    await page.getByLabel('类型', { exact: true }).selectOption(type);
    assert.equal(
      await agentTable.locator('tbody tr').count(),
      state.catalog.components.filter((item: any) => item.type === type).length,
    );
  }
  await page.getByLabel('类型', { exact: true }).selectOption('all');
  for (const agent of state.catalog.components) {
    await page.goto(origin + '/agents/' + agent.id);
    const configuration = page.getByLabel('Agent 完整配置', { exact: true });
    await configuration.waitFor();
    await configuration.locator('details').evaluate((element) => {
      (element as HTMLDetailsElement).open = true;
    });
    assert.deepEqual(
      JSON.parse(await configuration.locator('details pre').innerText()),
      state.catalog.definitions[agent.id],
    );
  }
  await page.goto(origin + '/agents');
  await agentTable.waitFor();
  await page.getByLabel('搜索 Agent').fill('tutoring.turn');
  assert.equal(await agentTable.locator('tbody tr').count(), 1);
  await agentTable
    .getByRole('link', { name: '启发式答疑', exact: true })
    .click();
  await page.waitForURL('**/agents/tutoring.turn');
  await page.getByLabel('Agent 完整配置', { exact: true }).waitFor();
  await page
    .getByLabel('Agent 完整配置', { exact: true })
    .locator('summary')
    .click();
  assert(
    (
      await page.getByLabel('Agent 完整配置', { exact: true }).innerText()
    ).includes('output_schema'),
  );
  await page.reload();
  await page.getByLabel('Agent 完整配置', { exact: true }).waitFor();
  const editButton = page.getByRole('button', {
    name: '编辑配置',
    exact: true,
  });
  assert.equal(
    await page
      .locator('.page-heading')
      .getByRole('button', { name: '编辑配置', exact: true })
      .count(),
    1,
  );
  const editBox = await editButton.boundingBox();
  const headingBox = await page.locator('.page-heading').boundingBox();
  assert(
    Math.abs(editBox!.x + editBox!.width - headingBox!.x - headingBox!.width) <
      2,
  );
  await page.getByRole('button', { name: '编辑配置' }).click();
  await page.waitForURL('**/agents/tutoring.turn?draft=*');
  const draftId = new URL(page.url()).searchParams.get('draft')!;
  const prompt = page.getByLabel('主Prompt', { exact: true });
  await prompt.waitFor();
  const nextPrompt = (await prompt.inputValue()) + '\n使用清晰的说明。';
  await prompt.fill(nextPrompt);
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '草稿已保存' }).waitFor();
  await page.reload();
  await page.getByLabel('主Prompt', { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel('主Prompt', { exact: true }).inputValue(),
    nextPrompt,
  );
  const saved = await (
    await page.request.get(origin + '/api/drafts/' + draftId)
  ).json();
  assert.equal(
    saved.bundle.files['agents/tutoring.turn.json'].prompt.template,
    nextPrompt,
  );
  await page.screenshot({
    path: '.local/agent-detail-edit.png',
    fullPage: true,
  });
  await page.getByRole('button', { name: '完整配置包', exact: false }).click();
  await page.waitForURL('**/drafts/' + draftId);
  await page.getByRole('button', { name: '校验配置', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '配置校验通过' }).waitFor();
  await nav.getByRole('button', { name: '发布管理', exact: false }).click();
  await page.waitForURL('**/releases');
  await page
    .getByRole('heading', { name: '待发布修改', exact: true })
    .waitFor();
  for (const [componentId, field] of [
    ['tutoring.leak-judge', '主Prompt'],
    ['tutoring.widget_guidelines', '工具静态正文'],
  ]) {
    await page.goto(origin + '/agents/' + componentId);
    await page.getByRole('button', { name: '编辑配置', exact: true }).click();
    await page.waitForURL('**/agents/' + componentId + '?draft=*');
    assert.equal(new URL(page.url()).searchParams.get('draft'), draftId);
    const input = page.getByLabel(field, { exact: true });
    await input.waitFor();
    await input.fill((await input.inputValue()) + '\n保持表述准确。');
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await page.getByRole('status').filter({ hasText: '草稿已保存' }).waitFor();
    await page.getByRole('button', { name: '校验配置', exact: true }).click();
    await page
      .getByRole('status')
      .filter({ hasText: '配置校验通过' })
      .waitFor();
  }
  await page.goto(origin + '/agents/planning.session-turn');
  await page.getByRole('button', { name: '编辑配置', exact: true }).click();
  await page.getByLabel('显示名称', { exact: true }).waitFor();
  const displayName = page.getByLabel('显示名称', { exact: true });
  await displayName.fill(
    (await displayName.inputValue()) === '计划会话执行器'
      ? '计划会话执行'
      : '计划会话执行器',
  );
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '草稿已保存' }).waitFor();
  await page.goto(origin + '/agents');
  await agentTable.waitFor();
  const latest = await (await page.request.get(origin + '/api/state')).json();
  assert(latest.drafts[0].changed_ids.length > 0);
  for (const component of latest.catalog.components) {
    const row = agentTable
      .locator('tbody tr')
      .filter({ has: page.getByText(component.id, { exact: true }) });
    assert.equal(
      (await row.innerText()).includes('有待发布修改'),
      latest.drafts[0].changed_ids.includes(component.id),
    );
  }
  await page.goto(origin + '/agents/no-such-agent');
  await page.getByRole('heading', { name: '未找到此配置' }).waitFor();
  await page.goto(origin + '/workflows');
  await page
    .getByRole('table', { name: 'Workflow 列表', exact: true })
    .waitFor();
  await nav.getByRole('button', { name: '发布管理', exact: false }).click();
  const versions = page.getByRole('table', { name: '发布版本', exact: true });
  await versions.waitFor();
  await versions
    .locator('tbody tr')
    .first()
    .getByRole('button', { name: '查看版本', exact: true })
    .click();
  await page.getByLabel('版本详情', { exact: true }).waitFor();
  await page.reload();
  await page.getByLabel('版本详情', { exact: true }).waitFor();
  await nav.getByRole('button', { name: '调试记录', exact: false }).click();
  const runs = page.getByRole('table', { name: '调试记录', exact: true });
  await runs.waitFor();
  assert.deepEqual(await runs.locator('th').allTextContents(), [
    '调试对象',
    '类型',
    '配置来源',
    '输入摘要',
    '结果 / 时间',
    '操作',
  ]);
  if (await runs.locator('tbody tr').count()) {
    await runs
      .locator('tbody tr')
      .first()
      .getByRole('button', { name: '查看详情' })
      .click();
    await page.getByLabel('调试详情', { exact: true }).waitFor();
  }
  await page.screenshot({ path: '.local/debug-records.png', fullPage: true });
  await nav.getByRole('button', { name: '发布管理', exact: false }).click();
  await page.getByRole('table', { name: '发布版本', exact: true }).waitFor();
  await page.screenshot({
    path: '.local/publication-manager.png',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  );
  await page.screenshot({
    path: '.local/workflow-table-mobile.png',
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    'table counts, direct detail URLs for all workflows, graph inspection, refresh/back, Agent full config and saved edits, whole-bundle draft validation, code component metadata editing, mobile: PASS',
  );
} finally {
  await browser.close();
}
