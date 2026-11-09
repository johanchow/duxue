import fs from 'node:fs';
import assert from 'node:assert/strict';
const origin = 'http://127.0.0.1:3021';
let cookie = '';
async function call(
  path: string,
  method = 'GET',
  body?: unknown,
  status = 200,
) {
  const response = await fetch(origin + '/api/' + path, {
    method,
    headers: {
      Origin: origin,
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
const state = await call('state');
const draft = await call(
  'drafts',
  'POST',
  { title: '完整配置 Admin 来源联调', from: 'server' },
  201,
);
assert.equal(draft.bundle.format_version, 3);
assert.equal(Object.keys(draft.bundle.files).length, 35);
const unit = draft.bundle.files['agents/companion.intent.json'];
unit.prompt.template += '\n保持原有意图分类与输出协议。';
unit.display_name = '对话意图路由';
const saved = await call('drafts/' + draft.id, 'PUT', {
  revision: draft.revision,
  bundle: draft.bundle,
});
await call(`drafts/${draft.id}/validate`, 'POST', { revision: saved.revision });
const tutor = await call(`drafts/${draft.id}/debug`, 'POST', {
  revision: saved.revision,
  input: {
    content: '请用两句话解释水为什么会蒸发。',
    component_id: 'tutoring-pipeline',
  },
});
assert.equal(tutor.status, 'succeeded');
const denied = await call(
  `drafts/${draft.id}/publish`,
  'POST',
  { revision: saved.revision, generation: state.environment.generation },
  409,
);
assert(denied.error.includes('companion.intent'));
const run = await call(`drafts/${draft.id}/debug`, 'POST', {
  revision: saved.revision,
  input: {
    content: JSON.stringify({
      content: '这道数学题怎么做？',
      focus_agent_type: null,
    }),
    component_id: 'companion.intent',
  },
});
assert.equal(run.status, 'succeeded');
assert(run.covered_components.includes('companion.intent'));
const release = await call(`drafts/${draft.id}/publish`, 'POST', {
  revision: saved.revision,
  generation: state.environment.generation,
});
let loaded;
for (let attempt = 0; attempt < 45; attempt++) {
  const current = await call('state');
  if (current.catalog.runtime.release_id === release.id) {
    loaded = current;
    break;
  }
  await new Promise((resolve) => setTimeout(resolve, 1000));
}
assert(loaded, 'server has not acknowledged complete release');
assert.equal(loaded.catalog.source, 'admin-release');
assert.equal(
  loaded.catalog.definitions['companion.intent'].prompt.template,
  unit.prompt.template,
);
const evidence = {
  release,
  manifest_files: 35,
  draft_id: draft.id,
  revision: saved.revision,
  debug: {
    companion: run.status,
    requests: run.model_requests,
    output: run.content,
    tokens_in: run.tokens_in,
    tokens_out: run.tokens_out,
  },
  runtime: loaded.catalog.runtime,
};
fs.writeFileSync(
  '.local/full-release-smoke.json',
  JSON.stringify(evidence, null, 2),
);
console.log(JSON.stringify(evidence, null, 2));
console.log(
  'complete artifact, exact-unit debug gate, real non-tutoring model, publish, server load and Admin-sourced detail: PASS',
);
