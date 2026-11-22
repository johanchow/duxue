type Doc = Record<string, any>;
export type ExecutionCall = {
  type: 'workflow';
  event: Doc;
  workflowId: string;
  rootIds: string[];
};
export type ExecutionChild = ExecutionCall | { type: 'event'; event: Doc };

export function nodeExecutions(events: Doc[], workflowId: string, node: Doc) {
  return events.filter(
    (event) =>
      event.kind !== 'edge' &&
      ((event.workflow_id === workflowId && event.node_id === node.id) ||
        (!event.node_id &&
          node.ref &&
          event.kind === 'model' &&
          event.unit_id === node.ref)),
  );
}
export function edgeExecutions(events: Doc[], workflowId: string, edge: Doc) {
  return events.filter(
    (event) =>
      event.kind === 'edge' &&
      event.workflow_id === workflowId &&
      event.from === edge.from &&
      event.to === edge.to &&
      (event.condition_id || null) === (edge.condition_id || null),
  );
}

/** Recorder events are ordered parent-first, including calls repeated within one turn. */
export function childExecution(events: Doc[], callId: string) {
  return descendants(events, new Set([callId]), false);
}

function descendants(
  events: Doc[],
  parents: Set<string>,
  includeRoots: boolean,
) {
  return events.filter((event) => {
    if (includeRoots && parents.has(event.id)) return true;
    if (!parents.has(event.parent_id)) return false;
    parents.add(event.id);
    return true;
  });
}

export function executionForCall(events: Doc[], call: ExecutionCall) {
  return descendants(events, new Set(call.rootIds), true);
}

export function executionChildren(
  events: Doc[],
  workflows: Record<string, Doc>,
  parent: Doc,
): ExecutionChild[] {
  const children: ExecutionChild[] = [];
  const calls = new Map<string, { call: ExecutionCall; atEntry: boolean }>();
  for (const event of events) {
    if (event.parent_id !== parent.id) continue;
    const workflowId = event.workflow_id;
    if (workflowId === parent.workflow_id || !workflows[workflowId]) {
      children.push({ type: 'event', event });
      continue;
    }

    // Older snapshots have no workflow node around the child execution.
    // A new START transition after a visit begins a separate invocation.
    const atEntry = event.kind === 'edge' && event.from === 'START';
    let current = calls.get(workflowId);
    if (!current || (atEntry && !current.atEntry)) {
      const call: ExecutionCall = {
        type: 'workflow',
        event,
        workflowId,
        rootIds: [],
      };
      current = { call, atEntry };
      calls.set(workflowId, current);
      children.push(call);
    }
    current.atEntry = atEntry;
    current.call.rootIds.push(event.id);
  }
  return children;
}

export function nodeVisits(events: Doc[], workflowId: string, node: Doc) {
  const matches = nodeExecutions(events, workflowId, node);
  const nestedModels = new Set(
    matches.flatMap((event) =>
      event.kind === 'model'
        ? []
        : childExecution(events, event.id)
            .filter((child) => child.kind === 'model')
            .map((child) => child.id),
    ),
  );
  return matches.filter((event) => !nestedModels.has(event.id));
}
