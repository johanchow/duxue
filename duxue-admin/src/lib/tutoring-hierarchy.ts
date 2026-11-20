import type { Json } from './workflow-graph';

export function tutoringHierarchy(workflows: Record<string, Json> = {}) {
  const flow = workflows.tutoring;
  const nodes: Json[] = flow?.nodes || [];
  const loop = nodes.find(
    (n) => n.id === 'tutoring.model_loop' && n.kind === 'workflow',
  );
  const attempt = nodes.find(
    (n) =>
      n.id === 'tutoring.attempt' &&
      n.parent === loop?.id &&
      n.kind === 'agent',
  );
  const exit = nodes.find(
    (n) => n.id === 'tutoring.exit_gate' && n.parent === attempt?.id,
  );
  const review = nodes.find(
    (n) =>
      n.id === 'tutoring.review_candidate' &&
      n.parent === exit?.id &&
      n.kind === 'workflow',
  );
  if (
    !loop ||
    !attempt ||
    !exit ||
    !review ||
    !workflows[loop.ref] ||
    !workflows[review.ref]
  )
    return null;
  return { loop, attempt, exit, review };
}

type Hierarchy = NonNullable<ReturnType<typeof tutoringHierarchy>>;

export function isTutoringAttempt(
  flow: Json,
  node: Json,
  hierarchy: Hierarchy | null,
) {
  return (
    flow.id === hierarchy?.loop.ref &&
    node.kind === 'action' &&
    [
      'primary',
      'repair',
      'backup',
      'visual_redraw',
      'missing_primary',
      'missing_backup',
    ].includes(node.handler_id)
  );
}

/** Collapse ownership only for display. Boundary edges retain their snapshot identity. */
export function tutoringOverview(flow: Json, hierarchy: Hierarchy) {
  const owner = hierarchy.loop.id;
  const nested = new Set<string>();
  const pending = [owner];
  while (pending.length) {
    const parent = pending.pop();
    for (const n of flow.nodes) {
      if (n.parent === parent && n.id !== owner && !nested.has(n.id)) {
        nested.add(n.id);
        pending.push(n.id);
      }
    }
  }
  return {
    ...flow,
    nodes: flow.nodes
      .filter((n: Json) => !nested.has(n.id))
      .map((n: Json) =>
        n.id === owner ? { ...n, display_name: '生成辅导回复' } : n,
      ),
    edges: flow.edges.flatMap((edge: Json) => {
      if (!nested.has(edge.from) && !nested.has(edge.to)) return [edge];
      const from = nested.has(edge.from) ? owner : edge.from;
      const to = nested.has(edge.to) ? owner : edge.to;
      return from === to ? [] : [{ ...edge, from, to, snapshotEdge: edge }];
    }),
  };
}
