import { langfuse } from './langfuse';
import { experimentIdentity } from './evaluation-model';
import { pool } from './db';
export async function evaluationResponse(request: Request, parts: string[]) {
  if (request.method !== 'GET')
    return Response.json({ error: '评测接口仅支持读取' }, { status: 405 });
  const page = parts[1];
  if (
    parts.length !== 2 ||
    !['overview', 'experiments', 'production'].includes(page)
  )
    return Response.json({ error: '页面不存在' }, { status: 404 });
  const params = new URL(request.url).searchParams,
    days = Number(params.get('days') || 7);
  if (!(page === 'experiments' ? [7, 30, 90] : [7, 30]).includes(days))
    return Response.json(
      { error: '指标支持7/30天，实验列表另支持90天' },
      { status: 400 },
    );
  try {
    const lf = langfuse(),
      common = {
        links: lf.links(),
        environment: lf.settings.environment,
        projectId: lf.settings.projectId,
        updatedAt: new Date().toISOString(),
        days,
      };
    if (page === 'production') {
      const [current, baselineResult] = await Promise.all([
        lf.summary('production', days),
        lf
          .summary('production', days, undefined, true)
          .then((value) => ({ value, error: null }))
          .catch((e: Error) => ({ value: null, error: e.message })),
      ]);
      return Response.json({
        ...common,
        current,
        baseline: baselineResult.value,
        warning: baselineResult.error
          ? `基线不可用：${baselineResult.error}；请检查 Langfuse 历史数据访问范围。`
          : null,
      });
    }
    const result = await lf.experiments({
      days,
      cursor: params.get('cursor') || undefined,
    });
    const experiments = await Promise.all(
      result.data.map(async (e: any) => {
        const identity = experimentIdentity(e.metadata);
        const releases = identity.configDigest
          ? (
              await pool().query(
                'SELECT id,sequence FROM agent_releases WHERE digest=$1 ORDER BY sequence DESC LIMIT 10',
                [identity.configDigest],
              )
            ).rows
          : [];
        const drafts = identity.configDigest
          ? (
              await pool().query(
                "SELECT id,title,revision FROM agent_drafts WHERE state='working' AND validation->>'digest'=$1",
                [identity.configDigest],
              )
            ).rows
          : [];
        return {
          drafts,
          id: e.id,
          name: e.name,
          startTime: e.startTime,
          itemCount: e.itemCount,
          datasetId: e.datasetId,
          identity,
          releases,
        };
      }),
    );
    if (page === 'experiments')
      return Response.json({
        ...common,
        experiments,
        cursor: result.meta?.cursor || null,
      });
    const currentId = params.get('current') || experiments[0]?.id,
      baselineId = params.get('baseline');
    // Only compare experiments in the selected result window; never silently substitute an ID.
    if (
      [currentId, baselineId].some(
        (id) => id && !experiments.some((e: any) => e.id === id),
      )
    )
      return Response.json(
        { error: '所选实验不在当前列表中，请调整时间范围或选择实验' },
        { status: 400 },
      );
    const [current, baseline] = await Promise.all([
      currentId ? lf.summary('experiment', days, currentId) : null,
      baselineId ? lf.summary('experiment', days, baselineId) : null,
    ]);
    return Response.json({
      ...common,
      experiments,
      currentId,
      baselineId,
      current,
      baseline,
    });
  } catch (e) {
    return Response.json({ error: (e as Error).message }, { status: 502 });
  }
}
