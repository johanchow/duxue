import { tutoringHierarchy, isTutoringAttempt } from "../src/lib/tutoring-hierarchy";
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { workflowGraph, workflowDetailHref } from '../src/lib/workflow-graph';
import { actionLogic, edgeConditionDetail, gateLogic } from '../src/lib/workflow-code';

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
test('gates and workflow actions have shareable details with the same draft', () => {
  const gate = { kind: 'gate', ref: 'tutoring.authority' };
  const judgeGate = { kind: 'gate', ref: 'tutoring.leak-judge' };
  assert.equal(
    workflowDetailHref('tutoring-vet', gate, { implementation: 'code' }),
    '/agents/tutoring.authority',
  );
  assert.equal(
    workflowDetailHref(
      'tutoring.review_candidate',
      judgeGate,
      { implementation: 'judge' },
      'draft/id',
    ),
    '/agents/tutoring.leak-judge?draft=draft%2Fid',
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
    '/agents/review',
  );
  assert.equal(workflowDetailHref('tutoring', { kind: 'gate' }), undefined);
  assert.equal(workflowDetailHref('tutoring', { kind: 'agent' }), undefined);
});

test('子流程卡片打开同一草稿或发布版本', () => {
  const node = {
    id: 'tutoring.model_loop',
    kind: 'workflow',
    ref: 'tutoring.model_loop',
    display_name: '答复生成与重试',
  };
  assert.ok(actionLogic(node.ref, { kind: 'action', handler_id: 'primary' })?.summary);
  assert.ok(edgeConditionDetail(node.ref, 'retry_leak')?.label);
  const graph = workflowGraph({ id: 'tutoring', nodes: [node], edges: [] });
  assert.equal(
    graph.nodes.find((n) => n.id === node.id)?.data.typeLabel,
    'Workflow · 子流程',
  );
  assert.equal(
    workflowDetailHref('tutoring', node, undefined, 'draft/a', 'r1'),
    '/workflows/tutoring.model_loop?draft=draft%2Fa',
  );
  assert.equal(
    workflowDetailHref('tutoring', node, undefined, undefined, 'r1'),
    '/workflows/tutoring.model_loop?release=r1',
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
  assert.deepEqual(graph.nodes.map(n => n.id), ['START', ...flow.nodes.map((n: any) => n.id), 'END']);
  assert.deepEqual(graph.edges.filter(e => !e.data?.relationship).map(e => [e.source, e.target]),
    flow.edges.map((e: any) => [e.from, e.to]));
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

test('导师重试线连接同一讲解节点的出口与入口，分支标签说明触发条件', () => {
  const prepare = 'guardian-mentor.prepare';
  const explain = 'guardian-mentor.explain';
  const solve = 'guardian-mentor.blueprint';
  const finish = 'guardian-mentor.finish';
  const flow = {
    id: 'guardian-mentor',
    nodes: [prepare, solve, explain, finish].map(id => ({ id, kind: 'action' })),
    edges: [
      { from: 'START', to: prepare },
      { from: prepare, to: solve, condition_id: 'solve' },
      { from: prepare, to: finish, condition_id: 'deliver' },
      { from: solve, to: explain },
      { from: explain, to: explain, condition_id: 'retry' },
      { from: explain, to: finish, condition_id: 'deliver' },
      { from: finish, to: 'END' },
    ],
  };
  for (const direction of ['LR', 'TB'] as const) {
    const { nodes, edges } = workflowGraph(flow, {}, {}, direction);
    const card = nodes.find(n => n.id === explain)!;
    const retry = edges.find(e => e.source === explain && e.target === explain)!;
    const points = retry.data!.route as { x: number; y: number }[];
    const anchors = card.handles!.map(h => ({ x: card.position.x + h.x!, y: card.position.y + h.y! }));
    assert.deepEqual(points[0], anchors[1]);
    assert.deepEqual(points.at(-1), anchors[0]);
    assert.match(String(retry.label), /重试/);
    assert.match(String(edges[1].label), /求解/);
    assert.match(String(edges[2].label), /安全|澄清/);
    assert.match(String(edges[5].label), /交付/);
  }
});

test('tutoring 主图可折叠非控制流归属子节点，并为主图和重试子图提供中文分支说明', () => {
  const flow = {
    id: 'tutoring',
    nodes: [
      { id: 'tutoring.turn', kind: 'action', handler_id: 'tutoring.turn' },
      { id: 'tutoring.intake', kind: 'action', handler_id: 'tutoring.intake' },
      { id: 'tutoring.model_loop', kind: 'workflow', ref: 'tutoring-retry' },
      {
        id: 'tutoring.attempt',
        kind: 'agent',
        ref: 'tutoring.turn',
        parent: 'tutoring.model_loop',
      },
      {
        id: 'tutoring.exit_gate',
        kind: 'action',
        handler_id: 'tutoring.exit_gate',
        parent: 'tutoring.attempt',
      },
      { id: 'tutoring.output_safety', kind: 'gate', ref: 'tutoring.output_safety' },
      { id: 'tutoring.apply_problem', kind: 'action', handler_id: 'tutoring.apply_problem' },
      { id: 'tutoring.result', kind: 'action', handler_id: 'tutoring.result' },
    ],
    edges: [
      { from: 'START', to: 'tutoring.turn' },
      { from: 'tutoring.turn', to: 'tutoring.intake', condition_id: 'open' },
      { from: 'tutoring.intake', to: 'tutoring.model_loop', condition_id: 'question' },
      { from: 'tutoring.model_loop', to: 'tutoring.output_safety' },
      { from: 'tutoring.output_safety', to: 'tutoring.apply_problem', condition_id: 'work' },
      { from: 'tutoring.apply_problem', to: 'tutoring.result' },
      { from: 'tutoring.result', to: 'END' },
    ],
  };
  const compact = workflowGraph(flow, {}, {}, 'LR', { showRelationships: false });
  assert.equal(compact.relationshipCount, 2);
  assert.equal(
    compact.edges.some((e) => e.data?.relationship),
    false,
  );
  assert.equal(
    compact.nodes.some((n) => n.id === 'tutoring.attempt' || n.id === 'tutoring.exit_gate'),
    false,
  );
  assert.equal(
    compact.edges.find(
      (e) => (e.data?.configuration as { condition_id?: string } | undefined)?.condition_id === 'work',
    )?.label,
    '通过 · 解题辅导',
  );
  assert.match(
    edgeConditionDetail('tutoring', 'work')?.summary || '',
    /TutoringProblem/,
  );
  assert.match(
    edgeConditionDetail('tutoring-retry', 'retry_leak')?.label || '',
    /修复重试/,
  );
});

test('候选回复审核使用同名草稿路由并保留审核边说明', () => {
  const id = 'tutoring.review_candidate';
  assert.equal(workflowDetailHref('tutoring', { kind: 'workflow', ref: id }, undefined, 'draft-2'),
    '/workflows/tutoring.review_candidate?draft=draft-2');
  const graph = workflowGraph({
    id,
    nodes: [{ id: id + '.authority', kind: 'gate', ref: 'tutoring.authority' }],
    edges: [{ from: id + '.authority', to: 'END', condition_id: 'authority_denied' }],
  });
  assert.equal(graph.edges[0].label, '权限拒绝');
  assert.ok(actionLogic(id, { kind: 'action', handler_id: 'tutoring.complete_vetting' })?.summary);
});

test('精简版 tutoring.model_loop 与新版 tutoring-blueprint 展示新增边标签', () => {
  assert.equal(edgeConditionDetail('tutoring.model_loop', 'needs_repair')?.label, '可自修失败，统一修复');
  assert.equal(edgeConditionDetail('tutoring.model_loop', 'accepted_or_terminal')?.label, '首轮通过/不可自修直出');
  assert.equal(edgeConditionDetail('tutoring-blueprint', 'needs_extract')?.label, '首次读题');
  assert.equal(edgeConditionDetail('tutoring-blueprint', 'has_verified_stem')?.label, '已有可信题面');
  assert.equal(edgeConditionDetail('tutoring-blueprint', 'worksheet_batch')?.label, '整页批改短路');
});
