'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { metricDelta, type Metric } from '../lib/evaluation-model';
import { IconArrowLeft, IconArrowRight, IconExternalLink } from './icons';
const format = (m: Metric) =>
  m.value === null
    ? '—'
    : `${m.unit === 'usd' ? '$' : ''}${m.value.toFixed(m.unit === 'usd' ? 4 : 1)}${m.unit === 'percent' ? '%' : m.unit === 'seconds' ? 's' : ''}`;
export function Evaluation({ page }: { page: string }) {
  const [days, setDays] = useState(7),
    [current, setCurrent] = useState(''),
    [baseline, setBaseline] = useState(''),
    [cursor, setCursor] = useState(''),
    [data, setData] = useState<any>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setData(null);
    const p = new URLSearchParams({ days: String(days) });
    if (current) p.set('current', current);
    if (baseline) p.set('baseline', baseline);
    if (cursor && page === 'experiments') p.set('cursor', cursor);
    fetch(`/api/evaluation/${page}?${p}`, { signal: controller.signal })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '读取失败');
        setData(d);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [page, days, current, baseline, cursor]);
  return (
    <section className="evaluation">
      <div className="eval-header">
        <nav className="eval-nav" aria-label="Evaluation 视图">
          {['overview', 'experiments', 'production'].map((p) => (
            <Link
              key={p}
              aria-current={page === p ? 'page' : undefined}
              href={`/evals/${p}`}
            >
              {p[0].toUpperCase() + p.slice(1)}
            </Link>
          ))}
        </nav>
        {data?.links && (
          <div className="eval-external" aria-label="Langfuse 外部入口">
            {Object.entries(data.links)
              .filter(([name]) => name !== 'Experiments')
              .map(([name, url]) => (
                <a
                  key={name}
                  className="button-link secondary btn-sm"
                  href={String(url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${name} ↗`}
                >
                  {name}
                  <IconExternalLink size={13} />
                </a>
              ))}
          </div>
        )}
      </div>
      <p className="muted">
        Langfuse 为评测数据源；配置与发布仍由 Admin
        管理。数据可能延迟，页面读取缓存最多 30 秒。Test Cases 位于 Datasets
        内。
      </p>
      <div className="eval-toolbar">
        <div className="eval-filters">
          <label>
            时间范围
            <select
              value={days}
              onChange={(e) => {
                setDays(Number(e.target.value));
                setCurrent('');
                setBaseline('');
                setCursor('');
              }}
            >
              {(page === 'experiments' ? [7, 30, 90] : [7, 30]).map((n) => (
                <option key={n} value={n}>
                  最近 {n} 天
                </option>
              ))}
            </select>
          </label>
          {page === 'overview' && data?.current && (
            <>
              <label>
                当前实验
                <select
                  value={current || data.currentId || ''}
                  onChange={(e) => setCurrent(e.target.value)}
                >
                  <option value="">选择实验</option>
                  {data.experiments.map((e: any) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                基线实验
                <select
                  value={baseline}
                  onChange={(e) => setBaseline(e.target.value)}
                >
                  <option value="">不比较</option>
                  {data.experiments.map((e: any) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>
        {data && (
          <span className="badge">
            项目 {data.projectId} ·{' '}
            {page === 'production' ? `环境 ${data.environment}` : '离线实验'}
          </span>
        )}
      </div>
      {loading && <p role="status">正在读取 Langfuse…</p>}
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {data && (
        <>
          {data.warning && (
            <p role="status" className="notice">
              {data.warning}
            </p>
          )}
          {page === 'experiments' ? (
            <>
              <div className="section-head">
                <div>
                  <h2>Experiments</h2>
                  <p className="compact-meta">
                    仅按配置 digest 精确关联发布记录；未提供摘要时不推测版本。
                  </p>
                </div>
                <div className="page-actions">
                  <a
                    className="button-link secondary btn-sm"
                    href={data.links.Experiments}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label="在 Langfuse 查看实验详情 ↗"
                  >
                    在 Langfuse 查看实验详情
                    <IconExternalLink size={13} />
                  </a>
                </div>
              </div>
              <div className="eval-table">
                <table>
                  <thead>
                    <tr>
                      <th>实验</th>
                      <th>用例数</th>
                      <th>版本标识</th>
                      <th>Admin 发布</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.experiments.map((e: any) => (
                      <tr key={e.id}>
                        <td>
                          {e.name}
                          <br />
                          <small>{e.startTime}</small>
                        </td>
                        <td>{e.itemCount ?? '—'}</td>
                        <td>
                          {Object.entries(e.identity).map(([k, v]) => (
                            <div key={k}>
                              <small>
                                {k}: {v ? String(v) : '未提供'}
                              </small>
                            </div>
                          ))}
                        </td>
                        <td>
                          {e.releases.length
                            ? e.releases.map((r: any) => (
                                <Link key={r.id} href={`/releases/${r.id}`}>
                                  R{r.sequence}{' '}
                                </Link>
                              ))
                            : '未关联发布'}
                          {e.drafts.map((d: any) => (
                            <div key={d.id}>
                              <Link href={`/drafts/${d.id}`}>
                                {d.title}（草稿 r{d.revision}）
                              </Link>
                            </div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!data.experiments.length && (
                <p className="empty">当前时间范围内没有 Langfuse 实验。</p>
              )}
              {(cursor || data.cursor) && (
                <div className="page-actions eval-pagination">
                  {cursor && (
                    <button
                      className="secondary btn-sm"
                      onClick={() => setCursor('')}
                    >
                      <IconArrowLeft size={14} />
                      返回第一页
                    </button>
                  )}
                  {data.cursor && (
                    <button
                      className="secondary btn-sm"
                      onClick={() => setCursor(data.cursor)}
                    >
                      下一页
                      <IconArrowRight size={14} />
                    </button>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              {!data.current ? (
                <p className="empty">
                  当前时间范围内没有实验。离线 runner 的本地报告不会自动成为
                  Langfuse 实验；请先在 Langfuse 建立并上报实验。
                </p>
              ) : (
                <>
                  <p>
                    {page === 'production'
                      ? '与前一个等长时间段比较。'
                      : '比较所选实验在当前时间范围内的数据。'}
                    任务根轮次数：{data.current.taskCount}；P95：
                    {data.current.p95Seconds?.toFixed(2) ?? '—'}s
                  </p>
                  <div className="eval-table">
                    <table>
                      <thead>
                        <tr>
                          <th>指标</th>
                          <th>Current</th>
                          <th>Δ</th>
                          <th>样本数</th>
                          <th>口径</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.current.metrics.map((m: Metric) => {
                          const b = data.baseline?.metrics.find(
                              (x: Metric) => x.id === m.id,
                            ),
                            delta = metricDelta(
                              m.value,
                              b?.value ?? null,
                              m.unit,
                            );
                          return (
                            <tr key={m.id}>
                              <td>{m.label}</td>
                              <td>{format(m)}</td>
                              <td>
                                {delta === null
                                  ? '—'
                                  : `${delta > 0 ? '+' : ''}${delta.toFixed(1)}${m.unit === 'percent' ? ' 个百分点' : m.unit === 'points' ? ' 分' : '%'}`}
                              </td>
                              <td>{m.samples}</td>
                              <td>{m.description}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p>
                    — 表示未上报、无有效样本或口径不匹配。独立裁判平均成本：
                    {data.current.gradingCost === null
                      ? '—'
                      : `$${data.current.gradingCost.toFixed(4)}`}
                  </p>
                  <p>
                    评测状态：
                    {Object.entries(data.current.status)
                      .map(([key, value]) => `${key}: ${value ?? '未上报'}`)
                      .join(' · ')}
                  </p>
                </>
              )}
            </>
          )}
          <small>读取时间：{new Date(data.updatedAt).toLocaleString()}</small>
        </>
      )}
    </section>
  );
}
