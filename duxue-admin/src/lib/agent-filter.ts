export type InventoryAgent = {
  id: string;
  name?: string;
  description?: string;
  type?: string;
  workflows?: string[];
};
/** Match catalog membership, including agents shared by several workflows. */
export function filterAgents<T extends InventoryAgent>(
  agents: T[],
  filters: { query: string; type: string; workflow: string },
): T[] {
  const query = filters.query.trim().toLowerCase();
  return agents.filter(
    (agent) =>
      (filters.type === 'all' || agent.type === filters.type) &&
      (filters.workflow === 'all' ||
        agent.workflows?.includes(filters.workflow)) &&
      `${agent.id} ${agent.name || ''} ${agent.description || ''}`
        .toLowerCase()
        .includes(query),
  );
}
