import {
  experimentQueries,
  productionQueries,
  periodSummary,
  type Query,
} from './evaluation-model';
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
  async summary(
    kind: 'production' | 'experiment',
    days: number,
    id?: string,
    previous = false,
  ) {
    return this.cached(
      `summary:${kind}:${days}:${id || ''}:${previous}`,
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
