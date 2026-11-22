import test from 'node:test';
import assert from 'node:assert/strict';
import {
  nodeExecutions,
  edgeExecutions,
  executionChildren,
  executionForCall,
  nodeVisits,
} from '../src/lib/execution-inspector';
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

test('shared solve agent records each model call on its executing node', () => {
  const events = ['ordinary', 'primary', 'alternative'].map((node_id) => ({
    workflow_id: 'blueprint',
    kind: 'model',
    node_id,
    unit_id: 'solver',
  }));
  assert.deepEqual(
    nodeExecutions(events, 'blueprint', { id: 'primary', ref: 'solver' }),
    [events[1]],
  );
});

test('历史回放只展开选中调用的后代事件', async () => {
  const { childExecution } = await import('../src/lib/execution-inspector');
  const events = [
    { id: '1' },
    { id: '2', parent_id: '1' },
    { id: '3', parent_id: '2' },
    { id: '4', parent_id: '1' },
    { id: '5', parent_id: '4' },
  ];
  assert.deepEqual(
    childExecution(events, '2').map((e) => e.id),
    ['3'],
  );
  assert.deepEqual(
    childExecution(events, '4').map((e) => e.id),
    ['5'],
  );
});

test('旧版调用证据按真实父子关系递归展开，重复子流程和并列打分互不串线', () => {
  const workflows = {
    retry: { nodes: [{ id: 'primary' }] },
    tutoring: { nodes: [{ id: 'attempt' }, { id: 'exit' }] },
    vet: { nodes: [{ id: 'judge' }] },
  };
  const events = [
    { id: '1', workflow_id: 'retry', node_id: 'primary', kind: 'action' },
    {
      id: '2',
      parent_id: '1',
      workflow_id: 'tutoring',
      node_id: 'attempt',
      kind: 'agent',
    },
    {
      id: '3',
      parent_id: '2',
      workflow_id: 'tutoring',
      node_id: 'attempt',
      kind: 'model',
      input: ['prompt'],
      output: 'draft',
    },
    {
      id: '4',
      parent_id: '2',
      workflow_id: 'tutoring',
      node_id: 'exit',
      kind: 'action',
    },
    {
      id: '5',
      parent_id: '4',
      workflow_id: 'vet',
      kind: 'edge',
      from: 'START',
      to: 'judge',
    },
    {
      id: '6',
      parent_id: '4',
      workflow_id: 'vet',
      node_id: 'judge',
      kind: 'gate',
    },
    {
      id: '7',
      parent_id: '6',
      workflow_id: 'vet',
      node_id: 'judge',
      kind: 'model',
      output: 'allow',
    },
    {
      id: '8',
      parent_id: '4',
      workflow_id: 'vet',
      kind: 'edge',
      from: 'START',
      to: 'judge',
    },
    {
      id: '9',
      parent_id: '4',
      workflow_id: 'vet',
      node_id: 'judge',
      kind: 'gate',
    },
    { id: '10', workflow_id: 'retry', node_id: 'other', kind: 'action' },
  ];
  const [attempt] = executionChildren(events, workflows, events[0]);
  assert(attempt.type === 'workflow');
  assert.equal(attempt.workflowId, 'tutoring');
  assert.deepEqual(
    executionForCall(events, attempt).map((e) => e.id),
    ['2', '3', '4', '5', '6', '7', '8', '9'],
  );
  const agenda = executionChildren(events, workflows, events[1]);
  assert.deepEqual(
    agenda.map((e) => [e.type, e.event.id]),
    [
      ['event', '3'],
      ['event', '4'],
    ],
  );
  assert.equal(agenda[0].event.output, 'draft');
  const judgments = executionChildren(events, workflows, events[3]);
  assert.deepEqual(
    judgments.map((entry) => {
      assert(entry.type === 'workflow');
      return executionForCall(events, entry).map((e) => e.id);
    }),
    [
      ['5', '6', '7'],
      ['8', '9'],
    ],
  );
});

test('显式子流程调用以该次调用为范围，仍保留节点自己的模型数据', () => {
  const workflows = {
    main: { nodes: [{ id: 'call', kind: 'workflow', ref: 'child' }] },
    child: { nodes: [{ id: 'agent', kind: 'agent', ref: 'model' }] },
  };
  const events = [
    { id: '1', workflow_id: 'main', node_id: 'call', kind: 'workflow' },
    {
      id: '2',
      parent_id: '1',
      workflow_id: 'child',
      node_id: 'agent',
      kind: 'agent',
    },
    {
      id: '3',
      parent_id: '2',
      workflow_id: 'child',
      node_id: 'agent',
      kind: 'model',
      input: ['request'],
      output: 'response',
    },
    { id: '4', workflow_id: 'main', node_id: 'call', kind: 'workflow' },
  ];
  const [child] = executionChildren(events, workflows, events[0]);
  assert(child.type === 'workflow');
  assert.equal(child.workflowId, 'child');
  assert.deepEqual(
    executionForCall(events, child).map((e) => e.id),
    ['2', '3'],
  );
  assert.equal(
    executionChildren(events, workflows, events[1])[0].event.output,
    'response',
  );
  assert.deepEqual(
    nodeVisits(events, 'child', workflows.child.nodes[0]).map((e) => e.id),
    ['2'],
  );
  assert.deepEqual(
    nodeVisits([events[2]], 'child', workflows.child.nodes[0]).map((e) => e.id),
    ['3'],
  );
  assert.deepEqual(executionChildren(events, workflows, events[3]), []);
});
