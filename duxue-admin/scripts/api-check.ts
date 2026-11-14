import fs from 'node:fs';
import assert from 'node:assert/strict';
const origin = 'http://127.0.0.1:3021';
let cookie = '';
async function request(
  path: string,
  method = 'GET',
  body?: unknown,
  expected = 200,
  site = origin,
  auth = true,
) {
  const response = await fetch(origin + '/api/' + path, {
    method,
    headers: {
      Origin: site,
      'Content-Type': 'application/json',
      Cookie: auth ? cookie : '',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (path === 'drafts' && method === 'POST' && expected === 201)
    assert([200, 201].includes(response.status), await response.clone().text());
  else assert.equal(response.status, expected, await response.clone().text());
  return response;
}
const login = await request(
  'session',
  'POST',
  JSON.parse(fs.readFileSync('.local/bootstrap.json', 'utf8')),
);
cookie = login.headers.get('set-cookie')!.split(';')[0];
assert(login.headers.get('set-cookie')?.includes('HttpOnly'));
await request('state', 'GET', undefined, 401, origin, false);
await request('internal/release', 'GET', undefined, 401);
await request('drafts', 'POST', {}, 403, 'https://other.test');
const before = await (await request('state')).json();
let draft = await (
  await request('drafts', 'POST', { title: 'API校验与并发回归' }, 201)
).json();
const originalBundle = structuredClone(draft.bundle);
const reopened = await (await request('drafts', 'POST', {}, 201)).json();
assert.equal(
  reopened.id,
  draft.id,
  'multiple create calls must share one working draft',
);
const responses = await Promise.all(
  [1, 2].map(() =>
    fetch(origin + '/api/drafts/' + draft.id, {
      method: 'PUT',
      headers: {
        Origin: origin,
        Cookie: cookie,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ revision: draft.revision, bundle: draft.bundle }),
    }),
  ),
);
assert.deepEqual(responses.map((r) => r.status).sort(), [200, 409]);
draft = await (await request('drafts/' + draft.id)).json();
assert.deepEqual(draft.bundle, originalBundle);
const behavioral = structuredClone(draft.bundle);
behavioral.files['agents/tutoring.turn.json'].models[0].temperature =
  behavioral.files['agents/tutoring.turn.json'].models[0].temperature === 0
    ? 0.1
    : 0;
draft = await (
  await request('drafts/' + draft.id, 'PUT', {
    revision: draft.revision,
    bundle: behavioral,
  })
).json();
await request(
  `drafts/${draft.id}/publish`,
  'POST',
  { revision: draft.revision, generation: before.environment.generation },
  409,
);
const invalid = structuredClone(draft.bundle);
invalid.files['agents/tutoring.turn.json'].output_schema = { type: 'object' };
draft = await (
  await request('drafts/' + draft.id, 'PUT', {
    revision: draft.revision,
    bundle: invalid,
  })
).json();
await request(
  `drafts/${draft.id}/validate`,
  'POST',
  { revision: draft.revision },
  422,
);
await request(
  `drafts/${draft.id}/publish`,
  'POST',
  { revision: draft.revision, generation: before.environment.generation },
  422,
);
const after = await (await request('state')).json();
assert.equal(before.environment.release_id, after.environment.release_id);
assert.equal(before.environment.generation, after.environment.generation);
draft = await (await request('drafts/' + draft.id)).json();
try {
  draft = await (
    await request('drafts/' + draft.id, 'PUT', {
      revision: draft.revision,
      bundle: draft.base_bundle,
    })
  ).json();
  await request(`drafts/${draft.id}/validate`, 'POST', {
    revision: draft.revision,
  });
  const unchanged = await request(
    `drafts/${draft.id}/publish`,
    'POST',
    { revision: draft.revision, generation: before.environment.generation },
    409,
  );
  assert((await unchanged.json()).error.includes('没有待发布的修改'));
} finally {
  draft = await (await request('drafts/' + draft.id)).json();
  await request('drafts/' + draft.id, 'PUT', {
    revision: draft.revision,
    bundle: originalBundle,
  });
}
console.log(
  'auth, CSRF, concurrent save, immutable contracts, configuration validation, unchanged active release: PASS',
);
