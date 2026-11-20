import { tutoringHierarchy, tutoringOverview, isTutoringAttempt } from "../src/lib/tutoring-hierarchy";
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { workflowGraph, workflowDetailHref } from '../src/lib/workflow-graph';
import { actionLogic, gateLogic } from '../src/lib/workflow-code';

const releaseSnapshot = JSON.parse(
  fs.readFileSync(
    path.resolve('../duxue-server/tests/fixtures/admin-release.json'),
    'utf8',
  ),
);
const snapshotWorkflows: Array<[string, any]> = Object.entries(
  releaseSnapshot.bundle.files,
)
  .filter(
    ([name]) => name.startsWith('workflows/') && name.endsWith('.json'),
  )
  .map(([name, doc]) => [path.basename(name), doc]);
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
for (const [file, flow] of snapshotWorkflows) {
  test(`${file}: graph preserves all control edges, branches, loops and unconnected child nodes`, () => {
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
  const flow = releaseSnapshot.bundle.files['workflows/tutoring-vet.json'];
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

test('parallel tutoring-vet topology renders Chinese labels for math/text/visual fan-out', () => {
  const flow = {
    kind: 'workflow',
    id: 'tutoring-vet',
    handler: 'tutoring',
    nodes: [
      { id: 'tutoring-vet.authority', kind: 'gate', ref: 'tutoring.authority' },
      { id: 'tutoring-vet.math_consistency', kind: 'gate', ref: 'tutoring.leak-judge' },
      { id: 'tutoring-vet.text_leak', kind: 'gate', ref: 'tutoring.leak-judge' },
      { id: 'tutoring-vet.visual_leak', kind: 'gate', ref: 'tutoring.visual-leak-judge' },
      { id: 'tutoring-vet.complete', kind: 'action', handler_id: 'tutoring.vet_complete' },
    ],
    edges: [
      { from: 'START', to: 'tutoring-vet.authority' },
      { from: 'tutoring-vet.authority', to: 'tutoring-vet.complete', condition_id: 'authority_denied' },
      { from: 'tutoring-vet.authority', to: 'tutoring-vet.complete', condition_id: 'authority_allowed_no_review' },
      { from: 'tutoring-vet.authority', to: 'tutoring-vet.math_consistency', condition_id: 'needs_math_review' },
      { from: 'tutoring-vet.authority', to: 'tutoring-vet.text_leak', condition_id: 'needs_text_review' },
      { from: 'tutoring-vet.authority', to: 'tutoring-vet.visual_leak', condition_id: 'needs_visual_review' },
      { from: 'tutoring-vet.math_consistency', to: 'tutoring-vet.complete' },
      { from: 'tutoring-vet.text_leak', to: 'tutoring-vet.complete' },
      { from: 'tutoring-vet.visual_leak', to: 'tutoring-vet.complete' },
      { from: 'tutoring-vet.complete', to: 'END' },
    ],
  };
  const { edges } = workflowGraph(flow);
  const labels = new Set(edges.map((edge) => edge.label).filter(Boolean));
  assert.ok(labels.has('并行：数学一致性'));
  assert.ok(labels.has('并行：正文答案保护'));
  assert.ok(labels.has('并行：配图答案保护'));
  assert.ok(labels.has('无需模型审核'));
  assert.ok(labels.has('权限拒绝'));
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

test('子流程卡片打开同一草稿或发布版本', () => {
  const node = {
    id: 'tutoring.model_loop',
    kind: 'workflow',
    ref: 'tutoring-retry',
    display_name: '生成与重试',
  };
  const graph = workflowGraph({ id: 'tutoring', nodes: [node], edges: [] });
  assert.equal(
    graph.nodes.find((n) => n.id === node.id)?.data.typeLabel,
    'Workflow · 子流程',
  );
  assert.equal(
    workflowDetailHref('tutoring', node, undefined, 'draft/a', 'r1'),
    '/workflows/tutoring-retry?draft=draft%2Fa',
  );
  assert.equal(
    workflowDetailHref('tutoring', node, undefined, undefined, 'r1'),
    '/workflows/tutoring-retry?release=r1',
  );
});

test('tutoring shows exit_gate in its declaring workflow and resolves the referenced retry attempts', () => {
  const workflows = Object.fromEntries(
    snapshotWorkflows.map(([, doc]) => [doc.id, structuredClone(doc)]),
  );
  assert.equal(tutoringHierarchy(workflows), null);
  const flow = workflows.tutoring;
  const loop = flow.nodes.find((n: any) => n.id === 'tutoring.model_loop');
  Object.assign(loop, { kind: 'workflow', ref: 'tutoring-retry' });
  flow.nodes.push({
    id: 'tutoring.review_candidate',
    parent: 'tutoring.exit_gate',
    kind: 'workflow',
    ref: 'tutoring-vet',
  });
  const hierarchy = tutoringHierarchy(workflows);
  assert.ok(hierarchy);
  const graph = workflowGraph(flow);
  assert.ok(graph.nodes.some(n => n.id === 'tutoring.exit_gate'));
  assert.ok(graph.edges.some(e => e.source === 'tutoring.exit_gate' && e.target === 'tutoring.output_safety'));
  assert.equal(graph.edges.filter(e => !e.data?.relationship).length, flow.edges.length);
  assert.equal(hierarchy.review.ref, 'tutoring-vet');
  assert.equal(hierarchy.exit.kind, 'action');
  const overview = workflowGraph(tutoringOverview(flow, hierarchy));
  assert.ok(!overview.nodes.some(n => n.id === hierarchy.exit.id));
  assert.equal(overview.nodes.find(n => n.id === loop.id)?.data.title, '生成辅导回复');
  const boundary = overview.edges.find(e => e.source === loop.id && e.target === 'tutoring.output_safety');
  assert.equal((boundary?.data?.configuration as any).from, hierarchy.exit.id);
  const retry = workflows[loop.ref];
  assert.deepEqual(
    retry.nodes
      .filter((n: any) => isTutoringAttempt(retry, n, hierarchy))
      .map((n: any) => n.handler_id),
    [
      'primary',
      'repair',
      'backup',
      'visual_redraw',
      'missing_primary',
      'missing_backup',
    ],
  );
  assert.equal(
    workflowDetailHref(retry.id, retry.nodes[0], undefined, undefined, 'r13'),
    '/workflows/tutoring-retry/nodes/tutoring-retry.primary?release=r13',
  );
});
