import dagre from '@dagrejs/dagre';
import { MarkerType, Position, type Node, type Edge } from '@xyflow/react';

export type Json = Record<string, any>;

/** Preserve every declared node/edge, including parallel branches and cycles.
 * Parent links are separate presentation relationships, never control edges. */
export function workflowGraph(
  flow: Json,
  definitions: Record<string, Json> = {},
) {
  const nodes: Node[] = [
    {
      id: 'START',
      position: { x: 0, y: 0 },
      data: { label: 'START · 入口' },
      className: 'boundary-node',
    },
    ...flow.nodes.map((node: Json) => ({
      id: node.id,
      position: { x: 0, y: 0 },
      data: {
        label: `${node.kind === 'action' ? 'Action · 固定代码' : node.kind === 'agent' ? `Agent · ${definitions[node.ref]?.implementation === 'code' ? '代码' : '模型'}` : `Gate · ${definitions[node.ref]?.implementation === 'judge' ? '模型 Judge' : '代码门禁'}`}${node.required ? ' · 必经' : ''}\n${definitions[node.ref]?.display_name || node.id}\n${node.ref || node.handler_id || ''}`,
      },
      className: `kind-${node.kind}`,
    })),
    {
      id: 'END',
      position: { x: 0, y: 0 },
      data: { label: 'END · 出口' },
      className: 'boundary-node',
    },
  ];
  const edges: Edge[] = flow.edges.map((edge: Json, index: number) => ({
    id: `edge-${index}`,
    source: edge.from,
    target: edge.to,
    label:
      flow.id === 'behavior-observation' && edge.condition_id
        ? (
            {
              eligible: '达到阈值且证据新鲜',
              ineligible: '未达条件，结束本次观察',
            } as Record<string, string>
          )[edge.condition_id] || edge.condition_id
        : edge.condition_id || '无条件',
    type: 'catalog',
    markerEnd: { type: MarkerType.ArrowClosed },
    data: { index, configuration: edge },
    interactionWidth: 24,
    labelStyle: { fontSize: 11 },
    style: { stroke: '#47826a', strokeWidth: 1.5 },
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
  graph.setGraph({ rankdir: 'LR', ranksep: 125, nodesep: 55, edgesep: 30 });
  graph.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((node) => graph.setNode(node.id, { width: 255, height: 90 }));
  [...edges, ...relationships].forEach((edge) =>
    graph.setEdge(
      edge.source,
      edge.target,
      {
        width: String(edge.label).length * 6.5 + 16,
        height: 24,
        labelpos: 'c',
      },
      edge.id,
    ),
  );
  dagre.layout(graph);
  nodes.forEach((node) => {
    const point = graph.node(node.id);
    node.position = { x: point.x - 127.5, y: point.y - 45 };
    node.sourcePosition = Position.Right;
    node.targetPosition = Position.Left;
    node.style = { width: 255, height: 90 };
  });
  const routedEdges: Edge[] = [...edges, ...relationships].map((edge) => {
    const route = graph.edge({ v: edge.source, w: edge.target, name: edge.id });
    return {
      ...edge,
      data: {
        ...edge.data,
        route: route.points,
        labelX: route.x,
        labelY: route.y,
      },
    };
  });
  return { nodes, edges: routedEdges };
}
