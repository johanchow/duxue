import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { workflowGraph, workflowDetailHref } from '../src/lib/workflow-graph';
import { actionLogic, gateLogic } from '../src/lib/workflow-code';

const directory = path.resolve(
  '../duxue-server/tests/fixtures/agent_specs/workflows',
);
test('code gates and workflow actions have shareable details with the same draft', () => {
  const gate = { kind: 'gate', ref: 'tutoring.authority' };
  assert.equal(
    workflowDetailHref('tutoring-vet', gate, { implementation: 'code' }),
    '/agents/tutoring.authority',
  );
  assert.equal(
    workflowDetailHref('tutoring-vet', gate, { implementation: 'judge' }),
    undefined,
  );
  assert.equal(
    workflowDetailHref(
      'tutoring',
      { kind: 'action', id: 'tutoring.model_loop' },
      undefined,
      'draft/id',
    ),
    '/workflows/tutoring/nodes/tutoring.model_loop?draft=draft%2Fid',
  );
});
for (const file of fs
  .readdirSync(directory)
  .filter((file) => file.endsWith('.json'))) {
  test(`${file}: graph preserves all control edges, branches, loops and unconnected child nodes`, () => {
    const flow = JSON.parse(
      fs.readFileSync(path.join(directory, file), 'utf8'),
    );
    const result = workflowGraph(flow);
    for (const node of flow.nodes.filter(
      (item: any) => item.kind === 'action',
    )) {
      assert.ok(actionLogic(flow.id, node)?.summary, `${flow.id}/${node.id}`);
    }
    assert.deepEqual(
      new Set(result.nodes.map((node) => node.id)),
      new Set(['START', 'END', ...flow.nodes.map((node: any) => node.id)]),
    );
    const controls = result.edges.filter((edge) => !edge.data?.relationship);
    assert.equal(controls.length, flow.edges.length);
    controls.forEach((edge, index) => {
      assert.deepEqual(edge.data?.configuration, flow.edges[index]);
      assert.equal(edge.source, flow.edges[index].from);
      assert.equal(edge.target, flow.edges[index].to);
    });
    assert.equal(
      new Set(result.edges.map((edge) => edge.id)).size,
      result.edges.length,
    );
    result.nodes.forEach((node) =>
      assert(
        Number.isFinite(node.position.x) && Number.isFinite(node.position.y),
      ),
    );
    result.edges
      .filter((edge) => edge.data?.relationship)
      .forEach((edge) => {
        assert.equal(
          flow.nodes.find((node: any) => node.id === edge.target).parent,
          edge.source,
        );
        assert.equal(edge.label, '归属（非控制流）');
      });
  });
}

test('parallel conditions have separate visible routes, including retry cycles', () => {
  const flow = JSON.parse(
    fs.readFileSync(path.join(directory, 'tutoring-vet.json'), 'utf8'),
  );
  const { edges } = workflowGraph(flow);
  const parallel = edges.filter(
    (edge) =>
      edge.source === 'tutoring-vet.authority' &&
      edge.target === 'tutoring-vet.complete',
  );
  assert.equal(parallel.length, 2);
  assert.notDeepEqual(parallel[0].data?.route, parallel[1].data?.route);
  edges.forEach((edge) => assert((edge.data?.route as any[]).length >= 2));
});

test('code gate explanations describe the registered handler only', () => {
  assert.match(
    gateLogic({
      implementation: 'code',
      handler_id: 'tutoring.check_authority',
    }) || '',
    /越权时拒绝候选/,
  );
  assert.equal(
    gateLogic({
      implementation: 'judge',
      handler_id: 'tutoring.check_authority',
    }),
    undefined,
  );
});

test('node labels distinguish model agents, code agents, judges and fixed code actions', () => {
  const flow = {
    nodes: [
      { id: 'model', kind: 'agent', ref: 'model-agent' },
      { id: 'code', kind: 'agent', ref: 'code-agent' },
      { id: 'judge', kind: 'gate', ref: 'judge' },
      { id: 'action', kind: 'action', handler_id: 'fixed' },
    ],
    edges: [
      { from: 'START', to: 'model' },
      { from: 'model', to: 'code' },
      { from: 'code', to: 'judge' },
      { from: 'judge', to: 'action' },
      { from: 'action', to: 'END' },
    ],
  };
  const { nodes } = workflowGraph(flow, {
    'model-agent': { implementation: 'llm' },
    'code-agent': { implementation: 'code' },
    judge: { implementation: 'judge' },
  });
  for (const [id, label] of [
    ['model', 'Agent · 模型'],
    ['code', 'Agent · 代码'],
    ['judge', 'Gate · 模型 Judge'],
    ['action', 'Action · 固定代码'],
  ]) {
    assert(
      String(nodes.find((node) => node.id === id)!.data.label).includes(label),
    );
  }
});

test('workflow cards prefer the snapshot name, then the inventory name, and keep type separate', () => {
  const flow = {
    nodes: [{ id: 'tutoring.attempt', kind: 'agent', ref: 'tutoring.turn' }],
    edges: [
      { from: 'START', to: 'tutoring.attempt' },
      { from: 'tutoring.attempt', to: 'END' },
    ],
  };
  const names = { 'tutoring.turn': '启发式答疑' };
  const definitions = { 'tutoring.turn': { implementation: 'llm' } };
  const card = workflowGraph(flow, definitions, names, 'TB').nodes[1];
  assert.equal(card.data.title, '启发式答疑');
  assert.equal(card.data.typeLabel, 'Agent · 模型');
  assert.equal(card.sourcePosition, 'bottom');
  assert.equal(
    workflowGraph(flow, { 'tutoring.turn': { display_name: '新导师' } }, names)
      .nodes[1].data.title,
    '新导师',
  );
  assert.equal(
    workflowDetailHref('tutoring', flow.nodes[0]),
    '/agents/tutoring.turn',
  );
  assert.equal(
    workflowDetailHref('tutoring', flow.nodes[0], undefined, 'draft/id'),
    '/agents/tutoring.turn?draft=draft%2Fid',
  );
  assert.equal(
    workflowDetailHref('tutoring', { kind: 'gate', ref: 'review' }),
    undefined,
  );
  assert.equal(workflowDetailHref('tutoring', { kind: 'agent' }), undefined);
});
