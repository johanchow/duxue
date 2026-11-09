import test from 'node:test';
import assert from 'node:assert/strict';
import { runTarget } from '../src/lib/run-target';
test('debug identity distinguishes the workflow, a model component and unknown historical ids', () => {
  assert.equal(runTarget({ input: {} }, null).type, '流程调试');
  const catalog = {
    components: [{ id: 'unit', name: '任务提取' }],
    definitions: {
      unit: { id: 'unit', models: [{ component_id: 'unit-backup' }] },
    },
  };
  assert.deepEqual(
    runTarget({ input: { component_id: 'unit-backup' } }, catalog),
    { id: 'unit-backup', name: '任务提取', type: '组件调试' },
  );
  assert.equal(
    runTarget({ input: { component_id: 'old-model' } }, catalog).id,
    'old-model',
  );
});
