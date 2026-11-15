import {
  batchQueries,
  experimentQueries,
  productionQueries,
  periodSummary,
  type Query,
} from './evaluation-model';
import {
  groupBatches,
  batchProjection,
  document,
  type Doc,
} from './evaluation-batches';
export type LangfuseSettings = {
  baseUrl: string;
  projectId: string;
  publicKey: string;
  secretKey: string;
  environment: string;
};
export class LangfuseReader {
  private cache = new Map<string, { expires: number; value: Promise<any> }>();
  constructor(
    readonly settings: LangfuseSettings,
    private fetcher: typeof fetch = fetch,
  ) {
    const u = new URL(settings.baseUrl);
    if (
      u.protocol !== 'https:' ||
      u.username ||
      u.password ||
      u.search ||
      u.hash
    )
      throw new Error('Langfuse 地址必须为 HTTPS');
  }
  private cached(key: string, read: () => Promise<any>) {
    const hit = this.cache.get(key);
    if (hit && hit.expires > Date.now()) return hit.value;
    if (this.cache.size >= 64)
      this.cache.delete(this.cache.keys().next().value!);
    const value = read().catch((e) => {
      this.cache.delete(key);
      throw e;
    });
    this.cache.set(key, { expires: Date.now() + 30000, value });
    return value;
  }
  private async request(path: string) {
    let response: Response;
    try {
      response = await this.fetcher(
        `${this.settings.baseUrl.replace(/\/$/, '')}/api/public/${path}`,
        {
          headers: {
            Authorization: `Basic ${Buffer.from(`${this.settings.publicKey}:${this.settings.secretKey}`).toString('base64')}`,
          },
          redirect: 'error',
          signal: AbortSignal.timeout(12000),
          cache: 'no-store',
        },
      );
    } catch {
      throw new Error('Langfuse 连接失败或超时');
    }
    if (!response.ok) throw new Error(`Langfuse API 返回 ${response.status}`);
    try {
      return await response.json();
    } catch {
      throw new Error('Langfuse 返回无效数据');
    }
  }
  private async verified() {
    await this.cached('project', async () => {
      const r = await this.request('projects');
      if (
        !r.data?.some((p: { id: string }) => p.id === this.settings.projectId)
      )
        throw new Error('Langfuse 凭证与配置的项目不匹配');
      return true;
    });
  }
  async experiments({ days, cursor }: { days: number; cursor?: string }) {
    return this.cached(`experiments:${days}:${cursor || ''}`, async () => {
      await this.verified();
      const p = new URLSearchParams({
        fromStartTime: new Date(Date.now() - days * 86400000).toISOString(),
        limit: '50',
        fields: 'metadata',
      });
      if (cursor) p.set('cursor', cursor);
      return this.request(`experiments?${p}`);
    });
  }
  private async pages(path: string, params: URLSearchParams) {
    const data: Doc[] = [],
      seen = new Set<string>();
    for (let page = 0; page < 200; page++) {
      const r = await this.request(`${path}?${params}`);
      if (!Array.isArray(r.data)) throw new Error('Langfuse分页结果无效');
      data.push(...r.data);
      const cursor = r.meta?.cursor;
      if (!cursor) return data;
      if (seen.has(cursor)) throw new Error('Langfuse分页游标重复');
      seen.add(cursor);
      params.set('cursor', cursor);
    }
    throw new Error('Langfuse结果超过读取上限，请缩小时间范围');
  }
  async batches(days: number) {
    return this.cached(`batches:${days}`, async () => {
      await this.verified();
      const all = await this.pages(
        'experiments',
        new URLSearchParams({
          fromStartTime: new Date(Date.now() - days * 86400000).toISOString(),
          fields: 'core,metadata',
          limit: '50',
        }),
      );
      return groupBatches(all);
    });
  }
  async batch(run: string, days: number) {
    return this.cached(`batch:${days}:${run}`, async () => {
      const group = (await this.batches(days)).find((b: Doc) => b.id === run);
      if (!group) throw new Error('批次不在当前时间范围内');
      const items: Doc[] = [];
      for (const e of group.experiments) {
        items.push(
          ...(await this.pages(
            'experiment-items',
            new URLSearchParams({
              experimentId: e.id,
              fromStartTime: new Date(
                Date.parse(e.startTime) - 1000,
              ).toISOString(),
              fields: 'core,io,itemMetadata,scores',
              limit: '50',
              scoreLimit: '20',
            }),
          )),
        );
      }
      return batchProjection(group, items);
    });
  }
  async evidence(run: string, itemId: string, days: number) {
    const batch = await this.batch(run, days);
    const item = batch.cases.find((c: Doc) => c.id === itemId);
    if (!item) throw new Error('用例不属于所选批次');
    return this.cached(`evidence:${run}:${itemId}`, async () => {
      const e = batch.experiments.find((e: Doc) => e.id === item.experimentId);
      const from = new Date(Date.parse(e.startTime) - 1000).toISOString();
      const to = new Date(
        Date.parse(e.endTime || e.startTime) + 3600000,
      ).toISOString();
      const observations = await this.pages(
        'v2/observations',
        new URLSearchParams({
          traceId: item.traceId,
          fromStartTime: from,
          toStartTime: to,
          fields: 'core,basic,io,metadata',
          limit: '50',
        }),
      );
      const scores = await this.pages(
        'v3/scores',
        new URLSearchParams({
          traceId: item.traceId,
          fields: 'core,details,subject',
          limit: '100',
        }),
      );
      const parse = (v: any) => {
        if (typeof v !== 'string') return v;
        try {
          return JSON.parse(v);
        } catch {
          return v;
        }
      };
      return {
        item,
        scores,
        observations: observations.map((o) => ({
          ...o,
          input: parse(o.input),
          output: parse(o.output),
        })),
      };
    });
  }
  async traceEvidence(traceId: string, date: string) {
    await this.verified();
    const from = new Date(`${date}T00:00:00Z`);
    const observations = await this.pages(
      'v2/observations',
      new URLSearchParams({
        traceId,
        fromStartTime: from.toISOString(),
        toStartTime: new Date(+from + 86400000).toISOString(),
        fields: 'core,basic,io,metadata',
        limit: '50',
        environment: this.settings.environment,
      }),
    );
    if (!observations.length)
      throw new Error('所选环境和日期没有该Trace的可见记录');
    return {
      observations: observations.map((o) => {
        let output = o.output;
        try {
          if (typeof output === 'string') output = JSON.parse(output);
        } catch {
          /* Preserve raw non-JSON model output. */
        }
        return { ...o, output };
      }),
    };
  }
  async summary(
    kind: 'production' | 'experiment',
    days: number,
    id?: string | string[],
    previous = false,
  ) {
    const key = Array.isArray(id) ? id.join(',') : id || '';
    return this.cached(
      `summary:${kind}:${days}:${key}:${previous}`,
      async () => {
        await this.verified();
        const to = new Date(
            Math.floor(Date.now() / 30000) * 30000 -
              (previous ? days * 86400000 : 0),
          ),
          from = new Date(to.getTime() - days * 86400000);
        const q =
          kind === 'production'
            ? productionQueries(
                this.settings.environment,
                from.toISOString(),
                to.toISOString(),
              )
            : Array.isArray(id)
              ? batchQueries(id, from.toISOString(), to.toISOString())
              : experimentQueries(id!, from.toISOString(), to.toISOString());
        const pairs = await Promise.all(
          Object.entries(q)
            .filter(([key]) => key !== 'trend')
            .map(async ([key, query]) => [
              key,
              (
                await this.request(
                  `v2/metrics?${new URLSearchParams({ query: JSON.stringify(query as Query) })}`,
                )
              ).data,
            ]),
        );
        const data = Object.fromEntries(pairs);
        return {
          ...periodSummary({
            ...data,
            offline: kind === 'experiment',
          } as Parameters<typeof periodSummary>[0]),
          from: from.toISOString(),
          to: to.toISOString(),
        };
      },
    );
  }
  async batchOverview(run: string, days: number) {
    return this.cached(`batch-overview:${days}:${run}`, async () => {
      const group = (await this.batches(days)).find((b: Doc) => b.id === run);
      if (!group) throw new Error('批次不在当前时间范围内');
      const ids = group.experiments.map((e: Doc) => e.id);
      const [summary, ...datasets] = await Promise.all([
        this.summary('experiment', days, ids),
        ...group.experiments.map(async (e: Doc) => ({
          id: e.id,
          name: e.name,
          dataset: e.name.includes('/') ? e.name.split('/').slice(1).join('/') : e.name,
          datasetId: e.datasetId,
          itemCount: e.itemCount ?? null,
          summary: await this.summary('experiment', days, e.id),
        })),
      ]);
      return { batch: group, summary, datasets };
    });
  }
  links() {
    const root = `${this.settings.baseUrl.replace(/\/$/, '')}/project/${encodeURIComponent(this.settings.projectId)}`;
    return {
      Datasets: `${root}/datasets`,
      Evaluators: `${root}/evals/v2`,
      'Human Review': `${root}/annotation-queues`,
      Experiments: `${root}/experiments`,
    };
  }
}
let reader: LangfuseReader | undefined,
  identity = '';
export function langfuse() {
  const settings = {
    baseUrl: process.env.ADMIN_LANGFUSE_BASE_URL || '',
    projectId: process.env.ADMIN_LANGFUSE_PROJECT_ID || '',
    publicKey: process.env.ADMIN_LANGFUSE_PUBLIC_KEY || '',
    secretKey: process.env.ADMIN_LANGFUSE_SECRET_KEY || '',
    environment: process.env.ADMIN_LANGFUSE_ENVIRONMENT || '',
  };
  if (Object.values(settings).some((v) => !v))
    throw new Error('请配置 Admin 的 Langfuse 连接和环境');
  const key = JSON.stringify(settings);
  if (!reader || identity !== key) {
    reader = new LangfuseReader(settings);
    identity = key;
  }
  return reader;
}
