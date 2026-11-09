/** URL state for shareable list and detail pages. */
export function studioRoute(pathname: string) {
  let parts: string[];
  try {
    parts = pathname.split('/').filter(Boolean).map(decodeURIComponent);
  } catch {
    return { tab: 'missing', id: undefined };
  }
  if (!parts.length) return { tab: 'flows', id: undefined };
  if (parts.length === 1) {
    return {
      tab:
        (
          {
            agents: 'agents',
            workflows: 'flows',
            drafts: 'config',
            runs: 'runs',
            releases: 'releases',
          } as Record<string, string>
        )[parts[0]] || 'missing',
      id: undefined,
    };
  }
  if (parts.length === 2)
    return {
      tab:
        (
          {
            agents: 'agent-detail',
            workflows: 'flow-detail',
            drafts: 'config',
            releases: 'release-detail',
          } as Record<string, string>
        )[parts[0]] || 'missing',
      id: parts[1],
    };
  return { tab: 'missing', id: undefined };
}
export const studioPaths: Record<string, string> = {
  agents: '/agents',
  flows: '/workflows',
  config: '/drafts',
  runs: '/runs',
  releases: '/releases',
};
