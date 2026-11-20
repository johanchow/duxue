type Doc = Record<string, any>;
export function nodeExecutions(events: Doc[], workflowId: string, node: Doc) {
  return events.filter(
    (event) =>
      event.kind !== 'edge' &&
      ((event.workflow_id === workflowId && event.node_id === node.id) ||
        (!event.node_id && node.ref && event.kind === 'model' && event.unit_id === node.ref)),
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
  const parents = new Set([callId]);
  return events.filter((event) => {
    if (!parents.has(event.parent_id)) return false;
    parents.add(event.id);
    return true;
  });
}
