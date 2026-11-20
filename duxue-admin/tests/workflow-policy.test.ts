import test from 'node:test';
import assert from 'node:assert/strict';
import { requireAuthorizedWorkflowChanges } from '../src/lib/workflow-policy';

test('Admin permits agent edits but rejects changes, additions and removal of workflow configurations', () => {
  const baseline = {
    files: {
      'agents/test.json': { prompt: 'original' },
      'workflows/test.json': { id: 'test', nodes: [], edges: [] },
    },
  };
  const edited = structuredClone(baseline);
  edited.files['agents/test.json'].prompt = 'changed';
  requireAuthorizedWorkflowChanges(edited, baseline);
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
    assert.throws(() => requireAuthorizedWorkflowChanges(changed, baseline), {
      status: 400,
    });
  }
});

test('only existing executable tutoring paths may change', () => {
  const path = 'workflows/tutoring.json';
  const baseline = {
    files: {
      [path]: { execution: 'turn_graph', nodes: ['a'], edges: [] as object[] },
    },
  };
  const edit = structuredClone(baseline);
  edit.files[path].edges.push({ from: 'a', to: 'END' });
  requireAuthorizedWorkflowChanges(edit, baseline);
  edit.files[path].nodes = [];
  assert.throws(() => requireAuthorizedWorkflowChanges(edit, baseline), {
    status: 400,
  });
});
