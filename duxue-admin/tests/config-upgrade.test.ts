import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assertUpgradeSource } from '../src/lib/config-upgrade';

test('offline upgrade refuses concurrent edits, changed release and unrelated draft', () => {
  const source = { kind: 'release' as const, id: 'r1', digest: 'digest1' };
  assert.doesNotThrow(() => assertUpgradeSource(source, undefined, source));
  assert.throws(
    () => assertUpgradeSource(source, { id: 'd1', revision: 2 }, source),
    /工作草稿/,
  );
  assert.throws(
    () =>
      assertUpgradeSource(source, undefined, { id: 'r2', digest: 'digest2' }),
    /基线/,
  );
  const draft = {
    kind: 'draft' as const,
    id: 'd1',
    digest: 'digest',
    revision: 3,
  };
  assert.doesNotThrow(() =>
    assertUpgradeSource(draft, { id: 'd1', revision: 3 }, source),
  );
  assert.throws(
    () => assertUpgradeSource(draft, { id: 'd1', revision: 4 }, source),
    /草稿已变化/,
  );
  assert.throws(
    () => assertUpgradeSource(draft, { id: 'd2', revision: 3 }, source),
    /草稿已变化/,
  );
  assert.throws(
    () => assertUpgradeSource(draft, undefined, source),
    /草稿已变化/,
  );
});

import { upgradedWorkflowBaseline } from '../src/lib/config-upgrade';
import { requireUnchangedWorkflows } from '../src/lib/workflow-policy';
test('validated migration adopts topology without erasing component change baseline', () => {
  const before = {
    files: {
      'agents/old.json': { prompt: 'old' },
      'workflows/old.json': { nodes: [] },
    },
  };
  const after = {
    files: {
      ...before.files,
      'agents/new.json': { prompt: 'new' },
      'workflows/new.json': { nodes: ['new'] },
    },
  };
  const baseline = upgradedWorkflowBaseline(before, after);
  assert.doesNotThrow(() => requireUnchangedWorkflows(after, baseline));
  assert.equal(baseline.files['agents/new.json'], undefined);
  assert.deepEqual(
    baseline.files['agents/old.json'],
    before.files['agents/old.json'],
  );
  assert.throws(() =>
    requireUnchangedWorkflows(
      { files: { ...after.files, 'workflows/new.json': { nodes: [] } } },
      baseline,
    ),
  );
});
