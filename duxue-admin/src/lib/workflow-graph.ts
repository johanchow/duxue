import dagre from '@dagrejs/dagre';
import { MarkerType, Position, type Node, type Edge } from '@xyflow/react';
import { actionLogic } from './workflow-code';

export type Json = Record<string, any>;

export function workflowNodeTitle(
  workflowId: string,
  node: Json,
  definition?: Json,
  catalogName?: string,
) {
  return (
    node.display_name?.trim() ||
    definition?.display_name?.trim() ||
    catalogName ||
    actionLogic(workflowId, node)?.title ||
    node.id
  );
}

export function workflowDetailHref(
  workflowId: string,
  node?: Json,
  definition?: Json,
  draftId?: string,
  releaseId?: string,
) {
  const query = draftId ? `?draft=${encodeURIComponent(draftId)}` : '';
  const snapshot =
    query || (releaseId ? `?release=${encodeURIComponent(releaseId)}` : '');
  if (node?.kind === 'workflow' && node.ref) {
    return `/workflows/${encodeURIComponent(node.ref)}${snapshot}`;
  }
  if (node?.kind === 'action')
    return `/workflows/${encodeURIComponent(workflowId)}/nodes/${encodeURIComponent(node.id)}${snapshot}`;
  if (
    node?.ref &&
    (node.kind === 'agent' ||
      (node.kind === 'gate' && definition?.implementation === 'code'))
  )
    return `/agents/${encodeURIComponent(node.ref)}${query}`;
}

function mentorBranchLabel(edge: Json) {
  if (edge.from === 'guardian-mentor.prepare') {
    if (edge.condition_id === 'solve') return '题目明确，进入求解';
    if (edge.condition_id === 'deliver') return '安全拦截或需要澄清';
  }
  if (edge.from === 'guardian-mentor.explain') {
    if (edge.condition_id === 'retry') return '讲解格式可修复，重试';
    if (edge.condition_id === 'deliver') return '结束讲解，进入交付';
  }
  return edge.condition_id;
}

/** Preserve every declared node/edge, including parallel branches and cycles.
 * Parent links are separate presentation relationships, never control edges. */
export function workflowGraph(
  flow: Json,
  definitions: Record<string, Json> = {},
  names: Record<string, string> = {},
  direction: 'LR' | 'TB' = 'LR',
) {
  const nodes: Node[] = [
    {
      id: 'START',
      position: { x: 0, y: 0 },
      data: { title: '开始' },
      className: 'boundary-node',
    },
    ...flow.nodes.map((node: Json) => {
      const definition = definitions[node.ref];
      const title = workflowNodeTitle(
        flow.id,
        node,
        definition,
        names[node.ref],
      );
      const typeLabel =
        node.kind === 'workflow'
          ? 'Workflow · 子流程'
          : node.kind === 'action'
            ? 'Action · 固定代码'
            : node.kind === 'agent'
              ? `Agent · ${definition?.implementation === 'code' ? '代码' : '模型'}`
              : `Gate · ${definition?.implementation === 'judge' ? '模型 Judge' : '代码门禁'}`;
      return {
        id: node.id,
        position: { x: 0, y: 0 },
        data: {
          title,
          typeLabel,
          label: `${title} · ${typeLabel}`,
          required: node.required,
          reference: node.ref || node.handler_id || node.id,
        },
        className: `kind-${node.kind}`,
      };
    }),
    {
      id: 'END',
      position: { x: 0, y: 0 },
      data: { title: '结束' },
      className: 'boundary-node',
    },
  ];
  const edges: Edge[] = flow.edges.map((edge: Json, index: number) => ({
    id: `edge-${index}`,
    source: edge.from,
    target: edge.to,
    label:
      flow.id === 'guardian-mentor' ? mentorBranchLabel(edge) :
      flow.id === 'behavior-observation' && edge.condition_id
        ? (
            {
              eligible: '达到阈值且证据新鲜',
              ineligible: '未达条件，结束本次观察',
            } as Record<string, string>
          )[edge.condition_id] || edge.condition_id
        : flow.id === 'tutoring-vet' && edge.condition_id
          ? (
              {
                authority_denied: '权限拒绝',
                authority_allowed_no_review: '无需模型审核',
                authority_allowed_no_leak_check: '无需模型审核',
                authority_allowed_needs_leak_check: '需答案保护审核',
                needs_math_review: '并行：数学一致性',
                needs_text_review: '并行：正文答案保护',
                needs_visual_review: '并行：配图答案保护',
                text_denied: '正文未通过',
                text_allowed_with_visual: '正文通过，检配图',
                text_allowed_no_visual: '正文通过，无配图',
              } as Record<string, string>
            )[edge.condition_id] || edge.condition_id
        : flow.id === 'tutoring-blueprint' && edge.condition_id
          ? (
              {
                complete: '题库命中 / T0 直答',
                ordinary: 'T1 普通题',
                complex: 'T2 并发双路',
                reread: '按需复读',
                disputed: '分歧短路',
                resume_select: '复读一致继续',
                backup: '证伪切异构备用',
                verified: '锚点核验通过',
                not_applicable: '无可算锚点',
                unknown: '核验未知',
              } as Record<string, string>
            )[edge.condition_id] || edge.condition_id
          : edge.condition_id || undefined,
    type: 'catalog',
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: '#71877d',
      width: 16,
      height: 16,
    },
    data: { index, configuration: edge },
    interactionWidth: 24,
    labelStyle: { fontSize: 11 },
    style: { stroke: '#71877d', strokeWidth: 1.5 },
  }));
  const linked = new Set(
    flow.edges.flatMap((edge: Json) => [edge.from, edge.to]),
  );
  const relationships: Edge[] = flow.nodes
    .filter((node: Json) => node.parent && !linked.has(node.id))
    .map((node: Json) => ({
      id: `parent-${node.id}`,
      source: node.parent,
      target: node.id,
      label: '归属（非控制流）',
      type: 'catalog',
      data: {
        relationship: true,
        configuration: { parent: node.parent, child: node.id },
      },
      style: { stroke: '#a0aaa5', strokeDasharray: '5 5' },
    }));
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({
    rankdir: direction,
    ranksep: direction === 'LR' ? 110 : 72,
    nodesep: 46,
    edgesep: 26,
  });
  graph.setDefaultEdgeLabel(() => ({}));
  const size = (node: Node) =>
    node.className === 'boundary-node'
      ? { width: 82, height: 42 }
      : { width: 238, height: 86 };
  nodes.forEach((node) => graph.setNode(node.id, size(node)));
  [...edges, ...relationships].forEach((edge) =>
    graph.setEdge(
      edge.source,
      edge.target,
      {
        width: edge.label ? Array.from(String(edge.label)).reduce((w, c) => w + (c.charCodeAt(0) > 127 ? 12 : 7), 16) : 0,
        height: edge.label ? 24 : 0,
        labelpos: 'c',
      },
      edge.id,
    ),
  );
  dagre.layout(graph);
  nodes.forEach((node) => {
    const point = graph.node(node.id);
    const { width, height } = size(node);
    node.position = { x: point.x - width / 2, y: point.y - height / 2 };
    node.sourcePosition = direction === 'LR' ? Position.Right : Position.Bottom;
    node.targetPosition = direction === 'LR' ? Position.Left : Position.Top;
    node.width = width;
    node.height = height;
    // Fixed cards can expose their connection points before the browser measures them.
    node.handles = [
      {
        id: 'in',
        type: 'target',
        position: node.targetPosition,
        x: direction === 'LR' ? 0 : width / 2,
        y: direction === 'LR' ? height / 2 : 0,
      },
      {
        id: 'out',
        type: 'source',
        position: node.sourcePosition,
        x: direction === 'LR' ? width : width / 2,
        y: direction === 'LR' ? height / 2 : height,
      },
    ];
    node.type = 'workflowCard';
  });
  const routedEdges: Edge[] = [...edges, ...relationships].map((edge) => {
    const route = graph.edge({ v: edge.source, w: edge.target, name: edge.id });
    let points = route.points;
    if (edge.source === edge.target) {
      // Dagre reserves a label lane for a self-edge but its polyline can miss both card handles.
      const { x, y, width, height } = graph.node(edge.source);
      const left = x - width / 2, right = x + width / 2;
      const top = y - height / 2, bottom = y + height / 2;
      const gap = 18;
      points = direction === 'LR'
        ? [{ x: right, y }, { x: right + gap, y }, { x: right + gap, y: route.y },
           { x: left - gap, y: route.y }, { x: left - gap, y }, { x: left, y }]
        : [{ x, y: bottom }, { x, y: bottom + gap }, { x: route.x, y: bottom + gap },
           { x: route.x, y: top - gap }, { x, y: top - gap }, { x, y: top }];
    }
    return {
      ...edge,
      data: {
        ...edge.data,
        route: points,
        labelX: route.x,
        labelY: route.y,
      },
    };
  });
  return { nodes, edges: routedEdges };
}
