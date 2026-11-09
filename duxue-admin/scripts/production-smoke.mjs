// Run inside the Admin Docker network with one-off bootstrap credentials.
import assert from 'node:assert/strict';
const base = process.env.ADMIN_TEST_BASE_URL || 'http://admin:3000';
const origin = 'https://admin.duxuelai.xyz';
let cookie = '';
async function request(path, method = 'GET', body, status = 200) {
  const r = await fetch(base + '/api/' + path, {
    method,
    headers: {
      origin,
      host: 'admin.duxuelai.xyz',
      'Content-Type': 'application/json',
      ...(cookie ? { cookie } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  assert.equal(r.status, status, `Unexpected status for ${path}: ${r.status}`);
  return r;
}
await request('state', 'GET', undefined, 401);
const login = await request('session', 'POST', {
  email: process.env.ADMIN_INIT_EMAIL,
  password: process.env.ADMIN_INIT_PASSWORD,
});
assert(login.headers.get('set-cookie').includes('Secure'));
cookie = login.headers.get('set-cookie').split(';')[0];
let state = await (await request('state')).json();
assert.equal(state.environment.name, 'prod');
assert.equal(state.user.role, 'admin');
assert.equal(state.catalogError, null);
assert.equal(Object.keys(state.catalog.bundle.files).length, 35);
if (!state.environment.release_id) {
  const draft = await (
    await request('drafts', 'POST', {}, state.drafts.length ? 200 : 201)
  ).json();
  await request(`drafts/${draft.id}/validate`, 'POST', {
    revision: draft.revision,
  });
  const run = await (
    await request(`drafts/${draft.id}/debug`, 'POST', {
      revision: draft.revision,
      input: {
        target_kind: 'agent',
        target_id: 'companion.intent',
        content: '我有一道数学题想请你给一点提示。',
      },
    })
  ).json();
  assert.equal(
    run.status,
    'succeeded',
    `Real model debug failed: ${run.failure || run.status}`,
  );
  assert.deepEqual(run.covered_components, ['companion.intent']);
  const release = await (
    await request(`drafts/${draft.id}/publish`, 'POST', {
      revision: draft.revision,
      generation: state.environment.generation,
    })
  ).json();
  console.log(
    'Initial production configuration published: R' + release.sequence,
  );
}
state = await (await request('state')).json();
const run = await (
  await request(`releases/${state.environment.release_id}/debug`, 'POST', {
    input: {
      target_kind: 'workflow',
      target_id: 'reflection',
      content: '今天我学会了乘法',
      context: { review_date: '2026-11-09', review_feeling: '开心' },
    },
  })
).json();
assert.equal(
  run.status,
  'succeeded',
  `Workflow debug failed: ${run.failure || run.status}`,
);
assert.equal(run.model_requests, 0);
assert.equal(run.output.run_status, 'closed');
assert.equal(run.source.kind, 'release');
assert.equal(
  run.sandbox_effects.self_reviews[0].reflection,
  '今天我学会了乘法',
);
const artifact = await (
  await request('releases/' + state.environment.release_id)
).json();
assert.equal(artifact.format_version, 3);
assert.equal(Object.keys(artifact.files).length, 35);
const denied = await fetch(base + '/api/drafts', {
  method: 'POST',
  headers: {
    cookie,
    origin: 'https://untrusted.example',
    'Content-Type': 'application/json',
  },
  body: '{}',
});
assert.equal(denied.status, 403);
const generation = state.environment.generation;
await request(`releases/${state.environment.release_id}/rollback`, 'POST', {
  generation,
});
await request(
  `releases/${state.environment.release_id}/rollback`,
  'POST',
  { generation },
  409,
);
assert.equal(
  (await (await request('state')).json()).environment.release_id,
  state.environment.release_id,
);
await request('session', 'DELETE');
console.log(
  'Production login, CSRF protection, isolated prod database, 35-file artifact and disposable Workflow execution: PASS',
);
