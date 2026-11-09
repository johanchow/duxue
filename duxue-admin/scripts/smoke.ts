import fs from 'node:fs';
import assert from 'node:assert/strict';
const origin = 'http://127.0.0.1:3021';
const credentials = JSON.parse(
  fs.readFileSync('.local/bootstrap.json', 'utf8'),
);
let cookie = '';
async function call(path: string, method = 'GET', body?: unknown) {
  const response = await fetch(origin + '/api/' + path, {
    method,
    headers: {
      Origin: origin,
      'Content-Type': 'application/json',
      Cookie: cookie,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (path === 'session' && method === 'POST')
    cookie = response.headers.get('set-cookie')?.split(';')[0] || '';
  const data = await response.json();
  if (!response.ok)
    throw new Error(response.status + ' ' + JSON.stringify(data));
  return data;
}
await call('session', 'POST', credentials);
const state = await call('state');
assert(!state.catalogError, state.catalogError);
const draft = await call('drafts', 'POST', {
  title: '完整 Agent 配置 · 联调验证',
  from: 'server',
});
const validation = await call(`drafts/${draft.id}/validate`, 'POST', {
  revision: draft.revision,
});
assert(validation.valid);
console.log('login, database, draft, Python validation passed');
const run = await call(`drafts/${draft.id}/debug`, 'POST', {
  revision: draft.revision,
  input: { content: '请用两句话解释水为什么会蒸发。', problem: '' },
});
console.log(
  JSON.stringify(
    {
      status: run.status,
      model_requests: run.model_requests,
      duration_ms: run.duration_ms,
      content: run.content,
    },
    null,
    2,
  ),
);
assert.equal(run.status, 'succeeded');
const release = await call(`drafts/${draft.id}/publish`, 'POST', {
  revision: draft.revision,
  generation: state.environment.generation,
});
fs.writeFileSync(
  '.local/smoke.json',
  JSON.stringify(
    {
      draft_id: draft.id,
      revision: draft.revision,
      release_id: release.id,
      run_id: run.id,
      digest: run.digest,
    },
    null,
    2,
  ),
);
console.log(
  'published R' + release.sequence + '; waiting for server acknowledgement',
);
