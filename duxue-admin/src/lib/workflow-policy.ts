import { isDeepStrictEqual } from 'node:util';
import { ApiError } from './auth';

// Read-only is a management policy. The baseline is the Admin draft/release,
// never a second copy of the topology in the Server repository.
export function requireUnchangedWorkflows(bundle: any, baseline: any) {
  const workflows = (value: any) =>
    Object.fromEntries(
      Object.entries(value?.files || {}).filter(([name]) =>
        name.startsWith('workflows/'),
      ),
    );
  if (!isDeepStrictEqual(workflows(bundle), workflows(baseline)))
    throw new ApiError(
      400,
      'Workflow 当前只支持查看，不能通过草稿修改流程配置',
    );
}
