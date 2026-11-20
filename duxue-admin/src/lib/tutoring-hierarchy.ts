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
