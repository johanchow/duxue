import fs from 'node:fs';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { config } from '../src/lib/config';
assert.equal(config().environment, 'test');
const credentials = JSON.parse(
  fs.readFileSync('.local/bootstrap.json', 'utf8'),
);
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
try {
  const page = await browser.newPage({
      viewport: { width: 1450, height: 1000 },
    }),
    errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:3021/evals/overview');
  await page.getByLabel('管理员邮箱').fill(credentials.email);
  await page.getByLabel('密码', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: '登录管理台 →' }).click();
  await page
    .getByRole('heading', { name: 'Evaluation', exact: true })
    .waitFor();
  for (const name of ['overview', 'experiments', 'production']) {
    await page.goto('http://127.0.0.1:3021/evals/' + name);
    await page
      .locator('.evaluation')
      .getByText(/读取时间：|Langfuse API 返回|连接失败或超时/)
      .waitFor({ timeout: 60000 });
    await page.screenshot({
      path: '.local/evaluation-' + name + '.png',
      fullPage: true,
    });
    const alert = page.locator('.evaluation [role=alert]');
    if (await alert.count()) throw new Error(await alert.innerText());
    assert.equal(await page.locator('iframe').count(), 0);
    assert.equal(
      await page
        .getByRole('link', { name: 'Human Review ↗', exact: true })
        .getAttribute('target'),
      '_blank',
    );
    assert.equal(await page.locator('.evaluation [role="alert"]').count(), 0);
    await page.screenshot({
      path: '.local/evaluation-' + name + '.png',
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: '.local/evaluation-mobile.png',
    fullPage: false,
  });
  assert.equal(
    await page
      .getByRole('link', { name: 'Test Cases ↗', exact: true })
      .count(),
    0,
  );
  assert.deepEqual(errors, []);
  console.log(
    'Real Langfuse read-only browser checks passed: 3 pages, external links, no iframe, mobile screenshot.',
  );
} finally {
  await browser.close();
}
