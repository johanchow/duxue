import test from 'node:test';
import assert from 'node:assert/strict';
import { requireUnchangedWorkflows } from '../src/lib/workflow-policy';

test('Admin permits agent edits but rejects changes, additions and removal of workflow configurations', () => {
  const baseline = {
    files: {
      'agents/test.json': { prompt: 'original' },
      'workflows/test.json': { id: 'test', nodes: [], edges: [] },
    },
  };
  const edited = structuredClone(baseline);
  edited.files['agents/test.json'].prompt = 'changed';
  requireUnchangedWorkflows(edited, baseline);
  for (const mutation of [
    (b: any) => {
      b.files['workflows/test.json'].edges.push({ from: 'START', to: 'END' });
    },
    (b: any) => {
      delete b.files['workflows/test.json'];
    },
    (b: any) => {
      b.files['workflows/extra.json'] = {};
    },
  ]) {
    const changed = structuredClone(baseline);
    mutation(changed);
    assert.throws(() => requireUnchangedWorkflows(changed, baseline), {
      status: 400,
    });
  }
});
