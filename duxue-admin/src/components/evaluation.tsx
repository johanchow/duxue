'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { metricDelta, type Metric } from '../lib/evaluation-model';
import { IconArrowLeft, IconArrowRight, IconExternalLink } from './icons';
import { EvaluationWorkbench } from './evaluation-workbench';
import { TraceExecutionLookup } from './workflow-execution';
const format = (m: Metric) =>
  m.value === null
    ? '—'
    : `${m.unit === 'usd' ? '$' : ''}${m.value.toFixed(m.unit === 'usd' ? 4 : 1)}${m.unit === 'percent' ? '%' : m.unit === 'seconds' ? 's' : ''}`;
export function Evaluation({ page }: { page: string }) {
  return page === 'overview' ? (
    <EvaluationWorkbench />
  ) : page === 'experiments' ? (
    <ExperimentsScores />
  ) : (
    <LegacyEvaluation page={page} />
  );
}
function rate(pass: number, total: number) {
  return total > 0 ? `${((pass / total) * 100).toFixed(1)}%` : '—';
}
function deltaRate(
  pass: number,
  total: number,
  bPass?: number,
  bTotal?: number,
) {
  if (bPass === undefined || bTotal === undefined || bTotal === 0 || total === 0)
    return '—';
  const d = (pass / total) * 100 - (bPass / bTotal) * 100;
  return `${d >= 0 ? '+' : ''}${d.toFixed(1)}pp`;
}
function ExperimentsScores() {
  const [days, setDays] = useState(7),
    [batches, setBatches] = useState<any[]>([]),
    [run, setRun] = useState(''),
    [baseline, setBaseline] = useState(''),
    [batchData, setBatchData] = useState<any>(null),
    [overviewData, setOverviewData] = useState<any>(null),
    [experimentsData, setExperimentsData] = useState<any>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError('');
    setBatches([]);
    setBatchData(null);
    setOverviewData(null);
    Promise.all([
      fetch(`/api/evaluation/batches?days=${days}`, { signal: abort.signal }).then(
        async (r) => {
          const d = await r.json();
          if (!r.ok) throw new Error(d.error || '读取批次失败');
          return d;
        },
      ),
      fetch(`/api/evaluation/experiments?days=${days}`, {
        signal: abort.signal,
      }).then(async (r) => {
        const d = await r.json();
        return r.ok ? d : null;
      }),
    ])
      .then(([bData, eData]) => {
        setBatches(bData.batches || []);
        setRun(bData.batches?.[0]?.id || '');
        setBaseline('');
        setExperimentsData(eData);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [days]);

  useEffect(() => {
    if (!run) return;
    const abort = new AbortController();
    setLoading(true);
    setError('');
    const metricDays = days > 30 ? 30 : days;
    Promise.all([
      fetch(
        `/api/evaluation/batch?${new URLSearchParams({ days: String(days), run, ...(baseline ? { baseline } : {}) })}`,
        { signal: abort.signal },
      ).then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '读取批次详情失败');
        return d;
      }),
      fetch(
        `/api/evaluation/overview?${new URLSearchParams({ days: String(metricDays), current: run, ...(baseline ? { baseline } : {}) })}`,
        { signal: abort.signal },
      ).then(async (r) => {
        const d = await r.json();
        return r.ok ? d : null;
      }),
    ])
      .then(([b, o]) => {
        setBatchData(b);
        setOverviewData(o);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [run, days, baseline]);

  const batch = batchData?.batch;
  const links = batchData?.links || experimentsData?.links;
  return (
    <section className="evaluation">
      <div className="eval-header">
        <nav className="eval-nav" aria-label="Evaluation 视图">
          {['overview', 'experiments', 'production'].map((p) => (
            <Link
              key={p}
              aria-current={p === 'experiments' ? 'page' : undefined}
              href={`/evals/${p}`}
            >
              {p[0].toUpperCase() + p.slice(1)}
            </Link>
          ))}
        </nav>
        {links && (
          <div className="eval-external" aria-label="Langfuse 外部入口">
            {Object.entries(links)
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
        从 Scores 与检查点维度展示各评分项、检查点组件的检查数与通过率。
      </p>
      <div className="eval-toolbar">
        <div className="eval-filters">
          <label>
            时间范围
            <select
              value={days}
              onChange={(e) => {
                setRun('');
                setDays(Number(e.target.value));
              }}
            >
              {[7, 30, 90].map((n) => (
                <option key={n} value={n}>
                  最近 {n} 天
                </option>
              ))}
            </select>
          </label>
          <label>
            评测批次
            <select value={run} onChange={(e) => setRun(e.target.value)}>
              <option value="">选择批次</option>
              {batches.map((b: any) => (
                <option key={b.id} value={b.id}>
                  {b.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            基线批次
            <select
              value={baseline}
              onChange={(e) => setBaseline(e.target.value)}
            >
              <option value="">不比较</option>
              {batches
                .filter((b: any) => b.id !== run)
                .map((b: any) => (
                  <option key={b.id} value={b.id}>
                    {b.id}
                  </option>
                ))}
            </select>
          </label>
        </div>
      </div>
      {loading && <p role="status">正在读取 Langfuse…</p>}
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {batch && (
        <>
          <h3>检查点维度（Score）通过率</h3>
          <div className="eval-table">
            <table>
              <thead>
                <tr>
                  <th>评分维度</th>
                  <th>检查数</th>
                  <th>通过数</th>
                  <th>通过率</th>
                  <th>不通过 / 异常 / 未执行</th>
                  {batchData.baseline && <th>对比基线</th>}
                </tr>
              </thead>
              <tbody>
                {(batch.scoreStats || []).map((s: any) => {
                  const bs = batchData.baseline?.scoreStats?.find(
                    (x: any) => x.name === s.name,
                  );
                  return (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td>{s.evaluated}</td>
                      <td>✅ {s.pass}</td>
                      <td>{rate(s.pass, s.evaluated)}</td>
                      <td>
                        ❌ {s.fail} · ⚠️ {s.error} · ⏸️ {s.not_run}
                      </td>
                      {batchData.baseline && (
                        <td>
                          {deltaRate(s.pass, s.evaluated, bs?.pass, bs?.evaluated)}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <h3>被测检查点组件分布</h3>
          <div className="eval-table">
            <table>
              <thead>
                <tr>
                  <th>被测组件 / 检查点类型</th>
                  <th>计划检查点</th>
                  <th>已执行</th>
                  <th>通过数</th>
                  <th>通过率</th>
                  <th>不通过 / 异常 / 未执行</th>
                  {batchData.baseline && <th>对比基线</th>}
                </tr>
              </thead>
              <tbody>
                {(batch.components || []).map((c: any) => {
                  const bc = batchData.baseline?.components?.find(
                    (x: any) => x.id === c.id,
                  );
                  return (
                    <tr key={c.id}>
                      <td>{c.id}</td>
                      <td>{c.planned}</td>
                      <td>{c.executed}</td>
                      <td>✅ {c.pass}</td>
                      <td>{rate(c.pass, c.executed)}</td>
                      <td>
                        ❌ {c.fail} · ⚠️ {c.error} · ⏸️ {c.not_run}
                      </td>
                      {batchData.baseline && (
                        <td>
                          {deltaRate(
                            c.pass,
                            c.executed,
                            bc?.pass,
                            bc?.executed,
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {overviewData?.current && (
        <>
          <h3>Scores 指标汇总</h3>
          <p>
            任务根轮次数：{overviewData.current.taskCount}；P95：
            {overviewData.current.p95Seconds?.toFixed(2) ?? '—'}s
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
                {overviewData.current.metrics.map((m: Metric) => {
                  const b = overviewData.baseline?.metrics.find(
                      (x: Metric) => x.id === m.id,
                    ),
                    delta = metricDelta(m.value, b?.value ?? null, m.unit);
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
        </>
      )}
      {experimentsData?.experiments?.length > 0 && (
        <details>
          <summary>
            Langfuse 实验与 Admin 发布关联（{experimentsData.experiments.length}
            ）
          </summary>
          <div className="eval-table">
            <table>
              <thead>
                <tr>
                  <th>实验</th>
                  <th>用例数</th>
                  <th>Admin 发布</th>
                </tr>
              </thead>
              <tbody>
                {experimentsData.experiments.map((e: any) => (
                  <tr key={e.id}>
                    <td>
                      {e.name}
                      <br />
                      <small>{e.startTime}</small>
                    </td>
                    <td>{e.itemCount ?? '—'}</td>
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
        </details>
      )}
    </section>
  );
}
function LegacyEvaluation({ page }: { page: string }) {
  const [days, setDays] = useState(7),
    [current, setCurrent] = useState(''),
    [baseline, setBaseline] = useState(''),
    [cursor, setCursor] = useState(''),
    [tab, setTab] = useState<'summary' | 'scores'>('summary'),
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
          {page === 'overview' && data?.batches?.length > 0 && (
            <>
              <label>
                当前批次
                <select
                  value={current || data.currentId || ''}
                  onChange={(e) => setCurrent(e.target.value)}
                >
                  <option value="">选择批次</option>
                  {data.batches.map((b: any) => (
                    <option key={b.id} value={b.id}>
                      {b.id} · {b.experiments.length}个Experiment
                      {b.expectedCases ? ` · ${b.expectedCases}例` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                基线批次
                <select
                  value={baseline}
                  onChange={(e) => setBaseline(e.target.value)}
                >
                  <option value="">不比较</option>
                  {data.batches.map((b: any) => (
                    <option key={b.id} value={b.id}>
                      {b.id} · {b.experiments.length}个Experiment
                      {b.expectedCases ? ` · ${b.expectedCases}例` : ''}
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
      {page === 'production' && <TraceExecutionLookup />}
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
                  当前时间范围内没有{page === 'overview' ? '评测批次' : '实验'}。离线 runner 的本地报告不会自动成为
                  Langfuse 实验；请先在 Langfuse 建立并上报实验。
                </p>
              ) : (
                <>
                  {page === 'overview' && data.currentBatch && (
                    <>
                      <div className="eval-counters">
                        <div className="eval-counter">
                          <strong>批次</strong>
                          <span>
                            {data.currentBatch.id} · {data.currentBatch.experiments.length} 个 Experiment
                            {data.currentBatch.expectedCases
                              ? `（期望 ${data.currentBatch.expectedCases} 例）`
                              : ''}
                          </span>
                        </div>
                        <div className="eval-counter">
                          <strong>任务结果</strong>
                          <span>
                            共 {data.current.taskCount} 例 · ✅ 通过{' '}
                            {data.current.status.pass ?? 0} · ❌ 不通过{' '}
                            {data.current.status.fail ?? 0} · ⚠️ 异常{' '}
                            {data.current.status.error ?? 0} · ⏸️ 未执行{' '}
                            {data.current.status.not_run ?? 0}
                          </span>
                        </div>
                        <div className="eval-counter">
                          <strong>关联配置与排查</strong>
                          <span>
                            {data.currentBatch.releases?.length
                              ? data.currentBatch.releases.map((r: any) => (
                                  <Link key={r.id} href={`/releases/${r.id}`}>
                                    R{r.sequence}{' '}
                                  </Link>
                                ))
                              : data.currentBatch.drafts?.length
                                ? data.currentBatch.drafts.map((d: any) => (
                                    <Link key={d.id} href={`/drafts/${d.id}`}>
                                      {d.title}（草稿 r{d.revision}）{' '}
                                    </Link>
                                  ))
                                : '未关联发布'}
                            {' · '}
                            <Link href="/evals/experiments">
                              前往 Experiments 排查明细 →
                            </Link>
                          </span>
                        </div>
                      </div>
                      <nav className="eval-nav" aria-label="Overview 视图">
                        <button
                          type="button"
                          className="secondary"
                          aria-pressed={tab === 'summary'}
                          onClick={() => setTab('summary')}
                        >
                          批次总览
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          aria-pressed={tab === 'scores'}
                          onClick={() => setTab('scores')}
                        >
                          各维度 Scores 拆解（{data.datasets?.length ?? 0}）
                        </button>
                      </nav>
                    </>
                  )}
                  {page === 'overview' && tab === 'scores' ? (
                    <div className="eval-table">
                      <table>
                        <thead>
                          <tr>
                            <th>Dataset</th>
                            <th>任务数 / 通过率</th>
                            <th>Teaching Correctness</th>
                            <th>Guidance Logic</th>
                            <th>Answer Protection</th>
                            <th>Safety</th>
                            <th>Tool Correctness</th>
                            <th>Latency</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(data.datasets || []).map((ds: any) => {
                            const bDs = (data.baselineDatasets || []).find(
                              (x: any) => x.dataset === ds.dataset,
                            );
                            const cell = (id: string) => {
                              const m = ds.summary.metrics.find(
                                (x: Metric) => x.id === id,
                              );
                              if (!m || m.value === null) return '—';
                              const bm = bDs?.summary.metrics.find(
                                (x: Metric) => x.id === id,
                              );
                              const d = metricDelta(
                                m.value,
                                bm?.value ?? null,
                                m.unit,
                              );
                              const deltaStr =
                                d === null
                                  ? ''
                                  : ` (${d > 0 ? '+' : ''}${d.toFixed(1)}${m.unit === 'percent' ? 'pp' : m.unit === 'points' ? '' : '%'})`;
                              return `${format(m)}${deltaStr} (n=${m.samples})`;
                            };
                            return (
                              <tr key={ds.id}>
                                <td>
                                  <strong>{ds.dataset}</strong>
                                  <br />
                                  <small>
                                    ✅ {ds.summary.status.pass ?? 0} · ❌{' '}
                                    {ds.summary.status.fail ?? 0} · ⚠️{' '}
                                    {ds.summary.status.error ?? 0}
                                  </small>
                                </td>
                                <td>
                                  {ds.summary.taskCount} 例 ·{' '}
                                  {cell('task_success')}
                                </td>
                                <td>{cell('teaching_correctness')}</td>
                                <td>{cell('guidance_logic')}</td>
                                <td>{cell('answer_protection')}</td>
                                <td>{cell('safety')}</td>
                                <td>{cell('tool_correctness')}</td>
                                <td>{cell('latency')}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <>
                      <p>
                        {page === 'production'
                          ? '与前一个等长时间段比较。'
                          : '比较所选批次在当前时间范围内聚合后的全部实验数据。'}
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
            </>
          )}
          <small>读取时间：{new Date(data.updatedAt).toLocaleString()}</small>
        </>
      )}
    </section>
  );
}
