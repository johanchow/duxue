import assert from 'node:assert/strict';
import { test } from 'node:test';
import { filterAgents } from '../src/lib/agent-filter';
const agents = [
  {
    id: 'shared',
    name: '图片准备',
    type: 'code-agent',
    workflows: ['observe', 'review'],
  },
  {
    id: 'vision',
    name: '活动解释',
    description: '可见活动',
    type: 'model-agent',
    workflows: ['observe'],
  },
  { id: 'report', name: '报告', type: 'code-agent', workflows: ['review'] },
  { id: 'detached', name: '独立组件', type: 'code-agent' },
];
test('workflow membership includes shared agents and combines query and type', () => {
  assert.deepEqual(
    filterAgents(agents, { query: '', type: 'all', workflow: 'observe' }).map(
      (a) => a.id,
    ),
    ['shared', 'vision'],
  );
  assert.deepEqual(
    filterAgents(agents, {
      query: ' 可见 ',
      type: 'model-agent',
      workflow: 'observe',
    }).map((a) => a.id),
    ['vision'],
  );
  assert.deepEqual(
    filterAgents(agents, { query: 'VISION', type: 'all', workflow: 'review' }),
    [],
  );
});
test('all workflows retains unassigned agents and supports empty results', () => {
  assert.equal(
    filterAgents(agents, { query: '', type: 'all', workflow: 'all' }).length,
    4,
  );
  assert.equal(
    filterAgents(agents, { query: '', type: 'all', workflow: 'removed' })
      .length,
    0,
  );
  assert.equal(
    filterAgents(agents, { query: '', type: 'code-agent', workflow: 'review' })
      .length,
    2,
  );
});
