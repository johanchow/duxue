import test from 'node:test';
import assert from 'node:assert/strict';
import {
  periodSummary,
  metricDelta,
  productionQueries,
  experimentIdentity,
} from '../src/lib/evaluation-model';
import { LangfuseReader } from '../src/lib/langfuse';
const settings = {
  baseUrl: 'https://langfuse.example',
  projectId: 'project-one',
  publicKey: 'pk-test',
  secretKey: 'sk-test',
  environment: 'production',
};
test('missing scores and cost remain unknown, zero is real, latency is milliseconds', () => {
  const s = periodSummary({
    taskCount: 4,
    root: [{ count_count: 4, p50_latency: 2800, p95_latency: 6000 }],
    numeric: [
      {
        name: 'eval.teaching_correctness',
        avg_value: 4,
        count_count: 3,
        min_value: 3,
        max_value: 5,
      },
      {
        name: 'eval.cost_per_task',
        avg_value: 0,
        count_count: 4,
        min_value: 0,
        max_value: 0,
      },
    ],
    boolean: [
      {
        name: 'eval.task_success',
        avg_value: 0,
        count_count: 2,
        min_value: 0,
        max_value: 0,
      },
    ],
    status: [],
  });
  assert.equal(s.metrics.find((m) => m.id === 'task_success')?.value, 0);
  assert.equal(
    s.metrics.find((m) => m.id === 'teaching_correctness')?.value,
    80,
  );
  assert.equal(s.metrics.find((m) => m.id === 'latency')?.value, 2.8);
  assert.equal(s.metrics.find((m) => m.id === 'cost')?.value, 0);
  assert.equal(s.metrics.find((m) => m.id === 'safety')?.value, null);
  assert.equal(metricDelta(90, 85, 'percent'), 5);
  assert.equal(metricDelta(2.8, 4, 'seconds'), -30.000000000000004);
  assert.equal(metricDelta(1, 0, 'usd'), null);
});
test('production isolates application roots and environment, score queries never substitute guardrail signals', () => {
  const q = productionQueries(
    'production',
    '2026-11-01T00:00:00Z',
    '2026-11-08T00:00:00Z',
  );
  assert.ok(
    q.root.filters.some((f) => f.column === 'name' && f.value === 'agent.turn'),
  );
  assert.ok(
    q.root.filters.some(
      (f) => f.column === 'isRootObservation' && f.value === true,
    ),
  );
  for (const x of Object.values(q))
    assert.ok(
      x.filters.some(
        (f) => f.column === 'environment' && f.value === 'production',
      ),
    );
  assert.equal(JSON.stringify(q).includes('tutor.check_pass'), false);
  assert.equal(
    experimentIdentity({ config_digest: 'a'.repeat(64) }).configDigest,
    'a'.repeat(64),
  );
  assert.equal(
    experimentIdentity({ config_digest: 'wrong' }).configDigest,
    null,
  );
});
test('client binds API key project, coalesces reads and never follows redirects with credentials', async () => {
  let calls = 0;
  const fetcher: typeof fetch = async (input, init) => {
    calls++;
    assert.equal(init?.redirect, 'error');
    assert.match(
      String(new Headers(init?.headers).get('Authorization')),
      /^Basic /,
    );
    return Response.json(
      String(input).endsWith('/projects')
        ? { data: [{ id: 'project-one' }] }
        : { data: [], meta: {} },
    );
  };
  const reader = new LangfuseReader(settings, fetcher);
  await Promise.all([
    reader.experiments({ days: 7 }),
    reader.experiments({ days: 7 }),
  ]);
  assert.equal(calls, 2);
  const wrong = new LangfuseReader(
    { ...settings, projectId: 'wrong' },
    fetcher,
  );
  await assert.rejects(wrong.experiments({ days: 7 }), /项目/);
  const fail = new LangfuseReader(
    settings,
    async () => new Response('secret upstream', { status: 401 }),
  );
  await assert.rejects(
    fail.experiments({ days: 7 }),
    (e) =>
      (e as Error).message.includes('401') &&
      !(e as Error).message.includes('secret upstream'),
  );
});
test('native scores use the two teaching dimensions and exclude grading wait from offline latency', () => {
  const q = productionQueries(
    'production',
    '2026-11-01T00:00:00Z',
    '2026-11-08T00:00:00Z',
  );
  assert.equal(JSON.stringify(q).includes('eval.answer_quality'), false);
  assert.ok(JSON.stringify(q.numeric).includes('EVAL'));
  const s = periodSummary({
    offline: true,
    root: [{ count_count: 1, p50_latency: 120000 }],
    numeric: [
      {
        name: 'eval.latency_ms',
        avg_value: 2800,
        min_value: 2800,
        max_value: 2800,
        count_count: 1,
      },
    ],
    boolean: [],
    status: [],
  });
  assert.equal(s.metrics.find((m) => m.id === 'latency')?.value, 2.8);
  assert.equal(s.p95Seconds, null);
  assert.ok(s.metrics.some((m) => m.id === 'guidance_logic'));
  assert.ok(s.metrics.some((m) => m.id === 'teaching_correctness'));
});
