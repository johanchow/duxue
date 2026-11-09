import fs from 'node:fs';
import assert from 'node:assert/strict';
const root = 'http://127.0.0.1:3021';
let cookie = '';
async function call(
  path: string,
  method = 'GET',
  body?: unknown,
  status = 200,
) {
  const response = await fetch(root + '/api/' + path, {
    method,
    headers: {
      Origin: root,
      Cookie: cookie,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (path === 'session')
    cookie = response.headers.get('set-cookie')!.split(';')[0];
  const data = await response.json();
  assert.equal(response.status, status, JSON.stringify(data));
  return data;
}
await call(
  'session',
  'POST',
  JSON.parse(fs.readFileSync('.local/bootstrap.json', 'utf8')),
);
async function edit() {
  const response = await fetch(root + '/api/drafts', {
    method: 'POST',
    headers: {
      Origin: root,
      Cookie: cookie,
      'Content-Type': 'application/json',
    },
    body: '{}',
  });
  assert([200, 201].includes(response.status));
  return response.json();
}
let state = await call('state');
let draft = await edit();
draft.bundle.files['agents/planning.session-turn.json'].display_name =
  '计划会话执行';
draft = await call('drafts/' + draft.id, 'PUT', {
  revision: draft.revision,
  bundle: draft.bundle,
});
await call(`drafts/${draft.id}/validate`, 'POST', { revision: draft.revision });
const metadata = await call(`drafts/${draft.id}/publish`, 'POST', {
  revision: draft.revision,
  generation: state.environment.generation,
});
const record = await call(`releases/${metadata.id}/detail`);
assert.equal(record.debug_run_id, null);
console.log('metadata publication without model calls: PASS');
state = await call('state');
draft = await edit();
const model = draft.bundle.files['agents/tutoring.turn.json'].models[1];
model.temperature = model.temperature === 0 ? 0.1 : 0;
draft = await call('drafts/' + draft.id, 'PUT', {
  revision: draft.revision,
  bundle: draft.bundle,
});
await call(`drafts/${draft.id}/validate`, 'POST', { revision: draft.revision });
const input = { content: '请用两句话解释水为什么会蒸发。' };
let result = await call(`drafts/${draft.id}/debug`, 'POST', {
  revision: draft.revision,
  input: { ...input, component_id: 'tutoring-pipeline' },
});
assert.equal(result.status, 'succeeded');
const blocked = await call(
  `drafts/${draft.id}/publish`,
  'POST',
  { revision: draft.revision, generation: state.environment.generation },
  409,
);
assert(blocked.error.includes('tutoring.turn-backup'));
result = await call(`drafts/${draft.id}/debug`, 'POST', {
  revision: draft.revision,
  input: { ...input, component_id: 'tutoring.turn-backup' },
});
assert.equal(result.status, 'succeeded');
assert(result.covered_components.includes('tutoring.turn-backup'));
const tested = await call(`drafts/${draft.id}/publish`, 'POST', {
  revision: draft.revision,
  generation: state.environment.generation,
});
state = await call('state');
await call(`releases/${metadata.id}/rollback`, 'POST', {
  generation: state.environment.generation,
});
fs.writeFileSync(
  '.local/publication-identity.json',
  JSON.stringify(
    {
      metadata,
      tested,
      current: metadata,
      coverage: result.covered_components,
    },
    null,
    2,
  ),
);
console.log(
  'backup-only change rejects primary-only evidence; actual backup debug, publication and rollback: PASS',
);
