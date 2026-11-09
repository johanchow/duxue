type Doc = Record<string, any>;
export function nodeExecutions(events: Doc[], workflowId: string, node: Doc) {
  return events.filter(
    (event) =>
      event.kind !== 'edge' &&
      ((event.workflow_id === workflowId && event.node_id === node.id) ||
        (node.ref && event.kind === 'model' && event.unit_id === node.ref)),
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
