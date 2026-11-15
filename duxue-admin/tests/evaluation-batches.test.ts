import test from 'node:test';
import assert from 'node:assert/strict';
import {
  groupBatches,
  batchProjection,
  compareBatches,
} from '../src/lib/evaluation-batches';
const raw = (id: string, value = 'fail', type = 'single_turn') => ({
  experimentId: id,
  id: `root-${id}`,
  traceId: id,
  experimentItemId: id,
  input: JSON.stringify({
    record: { id, type, checks: [{ id: 'one', component: 'tutoring.turn' }] },
  }),
  output: JSON.stringify({
    status: value,
    checks: [
      {
        check_id: 'one',
        status: value,
        grades: [{ name: 'q', status: value, value: 3 }],
      },
    ],
  }),
  expectedOutput: { checks: { one: { evaluators: { q: { min: 4 } } } } },
  scores: [
    {
      name: 'eval.status',
      source: 'API',
      subject: { id: `root-${id}` },
      value,
    },
  ],
});
test('batch counts tasks once, separates calibration and preserves stopped checkpoints', () => {
  const batch = groupBatches([
    {
      id: 'a',
      startTime: '2026-11-14',
      metadata: { run_id: 'run', case_count: 2 },
    },
    {
      id: 'b',
      startTime: '2026-11-14',
      metadata: { run_id: 'run', case_count: 2 },
    },
  ])[0];
  const a = raw('a');
  a.scores.push({ ...a.scores[0], subject: { id: 'child' }, value: 'pass' });
  const result = batchProjection(batch, [a, raw('b', 'pass', 'judge')]);
  assert.equal(result.complete, true);
  assert.equal(result.application.fail, 1);
  assert.equal(result.calibration.pass, 1);
  assert.equal(result.cases[0].firstFailure, 'one');
  assert.deepEqual(result.cases[0].failedDimensions, ['q']);
  assert.throws(() => batchProjection(batch, [a, a]), /重复/);
});
test('missing, duplicate and stale root status never appear as a confident pass', () => {
  const a = raw('a', 'pass');
  a.scores = [];
  const b = raw('b');
  b.scores.push(b.scores[0]);
  const c = raw('c');
  c.scores[0].value = 'pass';
  const r = batchProjection({ expectedCases: 4 }, [a, b, c]);
  assert.equal(r.complete, false);
  assert.equal(r.counts.unknown, 2);
  assert.equal(r.cases[2].snapshotCurrent, false);
  assert.deepEqual(r.cases[2].failedDimensions, []);
});
test('in-flight tasks with missing output stay visible as unknown', () => {
  const item = { ...raw('pending', 'pass'), output: null };
  const batch = batchProjection({ expectedCases: 1 }, [item]);
  assert.equal(batch.counts.unknown, 1);
  assert.equal(batch.checkpoints.unknown, 1);
  assert.equal(batch.components[0].executed, 0);
});
test('baseline matching requires identical cases and graders, preserves regressions', () => {
  const b = {
    expectedCases: 1,
    graderVersion: 'v1',
    codeVersion: 'commit',
    configDigest: 'config',
  };
  const current = batchProjection(b, [raw('a')]);
  const old = batchProjection(b, [raw('a', 'pass')]);
  assert.equal(compareBatches(current, old).changes?.[0].change, 'regression');
  old.cases[0].expected.checks.one.evaluators.q.min = 5;
  assert.equal(compareBatches(current, old).comparable, false);
  assert.equal(
    compareBatches(current, { ...old, graderVersion: 'v2' }).comparable,
    false,
  );
});

test('batch reader consumes cursors and evidence parses raw JSON without obsolete API flag', async () => {
  const { LangfuseReader } = await import('../src/lib/langfuse');
  let experimentPages = 0;
  const fetcher: typeof fetch = async (input) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith('/projects'))
      return Response.json({ data: [{ id: 'project' }] });
    if (url.pathname.endsWith('/experiments')) {
      experimentPages++;
      return Response.json({
        data: [
          {
            id: experimentPages === 1 ? 'one' : 'two',
            startTime: '2026-11-14T05:00:00Z',
            metadata: { run_id: 'run', case_count: 2 },
          },
        ],
        meta: experimentPages === 1 ? { cursor: 'next' } : {},
      });
    }
    if (url.pathname.endsWith('/experiment-items'))
      return Response.json({
        data: [raw(url.searchParams.get('experimentId')!)],
        meta: {},
      });
    if (url.pathname.endsWith('/v2/observations')) {
      assert.equal(url.searchParams.has('parseIoAsJson'), false);
      return Response.json({
        data: [
          {
            id: 'child',
            input: '[]',
            output: '{"response":{"message":"hello"}}',
          },
        ],
        meta: {},
      });
    }
    if (url.pathname.endsWith('/v3/scores'))
      return Response.json({ data: [], meta: {} });
    throw new Error('unexpected endpoint');
  };
  const reader = new LangfuseReader(
    {
      baseUrl: 'https://langfuse.example',
      projectId: 'project',
      publicKey: 'pk',
      secretKey: 'sk',
      environment: 'test',
    },
    fetcher,
  );
  const result = await reader.batch('run', 7);
  assert.equal(experimentPages, 2);
  assert.equal(result.cases.length, 2);
  const evidence = await reader.evidence('run', 'one', 7);
  assert.deepEqual(evidence.observations[0].input, []);
  assert.equal(evidence.observations[0].output.response.message, 'hello');
});

test('checkpoint display applies frozen thresholds and rejects missing or duplicate native grades', async () => {
  const { checkpointGrades } = await import('../src/lib/evaluation-batches');
  const check = {
    observation_id: 'child',
    requirement: { evaluators: { q: { min: 5 }, s: { equals: true } } },
  };
  const scores = [
    { name: 'q', source: 'EVAL', subject: { id: 'child' }, value: 4 },
  ];
  assert.deepEqual(
    checkpointGrades(check, scores).map((g) => g.status),
    ['fail', 'error'],
  );
  assert.equal(
    checkpointGrades(check, [...scores, ...scores])[0].status,
    'error',
  );
  assert.equal(
    checkpointGrades(
      { ...check, requirement: { evaluators: { q: { min: 0 } } } },
      scores,
    )[0].status,
    'error',
  );
});

test('batchProjection aggregates scoreStats per dimension across checkpoints', () => {
  const entry = {
    ...raw('c1', 'fail'),
    experimentId: 'e1',
    input: JSON.stringify({
      record: {
        id: 'c1',
        type: 'episode',
        checks: [
          { id: 'ch1', component: 'tutoring.turn' },
          { id: 'ch2', component: 'tutoring.turn' },
        ],
      },
    }),
    output: JSON.stringify({
      status: 'fail',
      checks: [
        {
          check_id: 'ch1',
          status: 'pass',
          grades: [
            { name: 'eval.safety', status: 'pass' },
            { name: 'eval.teaching_correctness', status: 'pass' },
          ],
        },
        {
          check_id: 'ch2',
          status: 'fail',
          grades: [
            { name: 'eval.safety', status: 'pass' },
            { name: 'eval.teaching_correctness', status: 'fail' },
          ],
        },
      ],
    }),
    expectedOutput: {
      checks: {
        ch1: {
          evaluators: {
            'eval.safety': { equals: true },
            'eval.teaching_correctness': { min: 4 },
          },
        },
        ch2: {
          evaluators: {
            'eval.safety': { equals: true },
            'eval.teaching_correctness': { min: 4 },
          },
        },
      },
    },
  };
  const b = batchProjection(
    { id: 'r1', expectedCases: 1, experiments: [{ id: 'e1', name: 'r1/ds1' }] },
    [entry],
  );
  const safety = b.scoreStats.find((s: any) => s.name === 'eval.safety');
  const teach = b.scoreStats.find(
    (s: any) => s.name === 'eval.teaching_correctness',
  );
  assert.deepEqual(safety, {
    name: 'eval.safety',
    planned: 2,
    evaluated: 2,
    pass: 2,
    fail: 0,
    error: 0,
    not_run: 0,
  });
  assert.deepEqual(teach, {
    name: 'eval.teaching_correctness',
    planned: 2,
    evaluated: 2,
    pass: 1,
    fail: 1,
    error: 0,
    not_run: 0,
  });
});
