import { isDeepStrictEqual } from 'node:util';
import { ApiError } from './auth';

const tutoring = 'workflows/tutoring.json';

export function requireAuthorizedWorkflowChanges(bundle: any, baseline: any) {
  const allowEdges = baseline?.files?.[tutoring]?.execution === 'turn_graph';
  const workflows = (value: any) =>
    Object.fromEntries(
      Object.entries(value?.files || {})
        .filter(([name]) => name.startsWith('workflows/'))
        .map(([name, doc]) => {
          if (
            allowEdges &&
            name === tutoring &&
            doc &&
            typeof doc === 'object'
          ) {
            const { edges, rollout_percent, ...contract } = doc as Record<
              string,
              unknown
            >;
            if (!Array.isArray(edges))
              throw new ApiError(400, '缺少答疑主流程路径');
            return [name, contract];
          }
          return [name, doc];
        }),
    );
  if (!isDeepStrictEqual(workflows(bundle), workflows(baseline)))
    throw new ApiError(400, '只能修改已升级答疑主流程的路径');
}
