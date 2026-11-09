import test from 'node:test';
import assert from 'node:assert/strict';
import { nodeExecutions, edgeExecutions } from '../src/lib/execution-inspector';
import { runTarget } from '../src/lib/run-target';
test('execution inspection preserves repeated calls and separates parallel edge conditions and workflows', () => {
  const events = [
    { id: '1', kind: 'agent', workflow_id: 'flow', node_id: 'flow.node' },
    { id: '2', kind: 'agent', workflow_id: 'flow', node_id: 'flow.node' },
    { id: '3', kind: 'agent', workflow_id: 'other', node_id: 'flow.node' },
    {
      id: '4',
      kind: 'edge',
      workflow_id: 'flow',
      from: 'a',
      to: 'b',
      condition_id: 'yes',
      selected: true,
    },
    {
      id: '5',
      kind: 'edge',
      workflow_id: 'flow',
      from: 'a',
      to: 'b',
      condition_id: 'no',
      selected: false,
    },
  ];
  assert.deepEqual(
    nodeExecutions(events, 'flow', { id: 'flow.node' }).map(
      (event) => event.id,
    ),
    ['1', '2'],
  );
  assert.deepEqual(
    edgeExecutions(events, 'flow', {
      from: 'a',
      to: 'b',
      condition_id: 'no',
    }).map((event) => event.id),
    ['5'],
  );
  assert.equal(nodeExecutions(events, 'flow', { id: 'unvisited' }).length, 0);
  assert.equal(
    runTarget(
      {
        input: {
          target_kind: 'agent',
          target_id: 'tutoring.turn',
          component_id: 'tutoring.turn-backup',
        },
      },
      null,
    ).id,
    'tutoring.turn',
  );
  assert.equal(
    runTarget(
      { input: { target_kind: 'workflow', target_id: 'reflection' } },
      null,
    ).type,
    '流程调试',
  );
});
