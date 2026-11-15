'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  statusLabels,
  checkpointGrades,
  type Doc,
} from '../lib/evaluation-batches';
import { metricDelta, type Metric } from '../lib/evaluation-model';
import { WorkflowExecution } from './workflow-execution';
import { DebugDrawer } from './debug-drawer';
import { IconExternalLink, IconEye, IconSearch } from './icons';

const formatMetric = (m: Metric) =>
  m.value === null
    ? '—'
    : `${m.unit === 'usd' ? '$' : ''}${m.value.toFixed(m.unit === 'usd' ? 4 : 1)}${m.unit === 'percent' ? '%' : m.unit === 'seconds' ? 's' : ''}`;

const pretty = (v: unknown) => JSON.stringify(v, null, 2);
async function read(path: string, signal?: AbortSignal) {
  const response = await fetch(`/api/evaluation/${path}`, { signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '读取失败');
  return data;
}
function rate(pass: number, total: number) {
  return total > 0 ? `${((pass / total) * 100).toFixed(1)}%` : '—';
}
function deltaPass(
  pass: number,
  total: number,
  bPass?: number,
  bTotal?: number,
) {
  if (bPass === undefined || bTotal === undefined || bTotal === 0 || total === 0)
    return '—';
  const dCount = pass - bPass;
  const dRate = (pass / total) * 100 - (bPass / bTotal) * 100;
  return `${dCount >= 0 ? '+' : ''}${dCount} 例 (${dRate >= 0 ? '+' : ''}${dRate.toFixed(1)}pp)`;
}
export function EvaluationWorkbench() {
  const [days, setDays] = useState(7),
    [batches, setBatches] = useState<Doc[]>([]);
  const [run, setRun] = useState(''),
    [baseline, setBaseline] = useState('');
  const [data, setData] = useState<Doc | null>(null),
    [error, setError] = useState('');
  const [view, setView] = useState('failures'),
    [dataset, setDataset] = useState(''),
    [component, setComponent] = useState(''),
    [search, setSearch] = useState('');
  const [item, setItem] = useState<Doc | null>(null);
  const [status, setStatus] = useState('');
  const [links, setLinks] = useState<Doc | null>(null);
  const [scoresData, setScoresData] = useState<Doc | null>(null);
  const [scoresError, setScoresError] = useState('');
  const [scoresLoading, setScoresLoading] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    setBatches([]);
    setData(null);
    read(`batches?days=${days}`, abort.signal)
      .then((d) => {
        setBatches(d.batches);
        if (d.links) setLinks(d.links);
        setRun(d.batches[0]?.id || '');
        setBaseline('');
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      });
    return () => abort.abort();
  }, [days]);
  useEffect(() => {
    if (view !== 'scores' || !run) return;
    const abort = new AbortController();
    setScoresLoading(true);
    setScoresError('');
    const metricDays = days > 30 ? 30 : days;
    read(
      `overview?${new URLSearchParams({ days: String(metricDays), current: run, ...(baseline ? { baseline } : {}) })}`,
      abort.signal,
    )
      .then(setScoresData)
      .catch((e) => {
        if (e.name !== 'AbortError') setScoresError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setScoresLoading(false);
      });
    return () => abort.abort();
  }, [view, run, days, baseline]);
  useEffect(() => {
    if (!run) return;
    const abort = new AbortController();
    setError('');
    setData(null);
    setItem(null);
    read(
      `batch?${new URLSearchParams({ days: String(days), run, ...(baseline ? { baseline } : {}) })}`,
      abort.signal,
    )
      .then(setData)
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      });
    return () => abort.abort();
  }, [run, days, baseline]);
  const batch = data?.batch;
  const rows =
    batch?.cases.filter(
      (c: Doc) =>
        (view !== 'failures' || c.status !== 'pass') &&
        (!status || c.status === status) &&
        (!dataset || c.experimentId === dataset) &&
        (!component || c.components.includes(component)) &&
        (!search || c.caseId.toLowerCase().includes(search.toLowerCase())),
    ) || [];
  return (
    <section className="evaluation">
      <div className="eval-header">
        <nav className="eval-nav" aria-label="Evaluation 视图">
          {['overview', 'experiments', 'production'].map((p) => (
            <Link
              key={p}
              aria-current={p === 'overview' ? 'page' : undefined}
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
        以评测批次维度展示全部评测与失败定位；Langfuse 为数据源，配置与发布仍由
        Admin 管理。
      </p>
      <div className="eval-toolbar eval-filters">
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
                最近{n}天
              </option>
            ))}
          </select>
        </label>
        <label>
          评测批次
          <select
            value={run}
            onChange={(e) => {
              setRun(e.target.value);
              setDataset('');
              setComponent('');
            }}
          >
            <option value="">选择批次</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.id} · {b.experiments.length}个Experiment
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
              .filter((b) => b.id !== run)
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {b.id}
                </option>
              ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {!error && run && !data && <p role="status">正在读取整批用例…</p>}
      {!run && !batches.length && !error && <p>当前时间范围内尚无可用批次。</p>}
      {batch && (
        <>
          <p>
            已记录 {batch.cases.length} / {batch.expectedCases ?? '未知'} 条用例
            · {batch.complete ? '数量完整' : '⚠️ 批次未完整或版本不一致'}
          </p>
          <details>
            <summary>本次配置与裁判版本</summary>
            <pre>
              {pretty({
                configDigest: batch.configDigest,
                codeVersion: batch.codeVersion,
                graderVersion: batch.graderVersion,
              })}
            </pre>
          </details>
          <div className="eval-counters">
            <div className="eval-counter">
              <strong>总评测数</strong>
              <span>
                {batch.cases.length} 例
                {data.baseline ? `（基线 ${data.baseline.total} 例）` : ''}
              </span>
            </div>
            <div className="eval-counter">
              <strong>通过评测数</strong>
              <span>
                ✅ {batch.counts.pass ?? 0} / {batch.cases.length}（
                {rate(batch.counts.pass ?? 0, batch.cases.length)}）
                {data.baseline
                  ? ` · 对比基线 ${deltaPass(batch.counts.pass ?? 0, batch.cases.length, data.baseline.counts?.pass, data.baseline.total)}`
                  : ''}
              </span>
            </div>
            <div className="eval-counter">
              <strong>未通过与异常</strong>
              <span>
                ❌ {batch.counts.fail ?? 0} · ⚠️ {batch.counts.error ?? 0} · ⏸️{' '}
                {batch.counts.not_run ?? 0}
              </span>
            </div>
          </div>
          {batch.datasets?.length > 0 && (
            <div className="eval-table">
              <table>
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>评测数</th>
                    <th>通过数</th>
                    <th>通过率</th>
                    <th>不通过 / 异常</th>
                    {data.baseline && <th>对比基线</th>}
                  </tr>
                </thead>
                <tbody>
                  {batch.datasets.map((ds: Doc) => {
                    const bDs = data.baseline?.datasets?.find(
                      (x: Doc) => x.name === ds.name,
                    );
                    return (
                      <tr key={ds.id}>
                        <td>
                          <button
                            type="button"
                            className="secondary btn-sm"
                            onClick={() =>
                              setDataset((prev) =>
                                prev === ds.id ? '' : ds.id,
                              )
                            }
                          >
                            {ds.name}
                          </button>
                        </td>
                        <td>{ds.total}</td>
                        <td>✅ {ds.pass ?? 0}</td>
                        <td>{rate(ds.pass ?? 0, ds.total)}</td>
                        <td>
                          ❌ {ds.fail ?? 0} · ⚠️ {ds.error ?? 0}
                        </td>
                        {data.baseline && (
                          <td>
                            {deltaPass(
                              ds.pass ?? 0,
                              ds.total,
                              bDs?.pass,
                              bDs?.total,
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">
            自动语义评分未校准。质量不通过、执行异常和未执行分别展示；组件归属不等于故障责任。
          </p>
          <nav className="eval-nav" aria-label="批次视图">
            {[
              ['failures', '失败与异常'],
              ['all', '全部用例'],
              ['scores', 'Scores 指标'],
              ['agents', '组件效果与覆盖'],
            ].map(([v, label]) => (
              <button
                key={v}
                className="secondary"
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {label}
              </button>
            ))}
          </nav>
          {view === 'scores' ? (
            <>
              {scoresLoading && <p role="status">正在读取 Scores 指标…</p>}
              {scoresError && (
                <p role="alert" className="notice error">
                  {scoresError}
                </p>
              )}
              {scoresData?.current && (
                <>
                  <p>
                    {days > 30
                      ? '指标聚合窗口上限为最近 30 天。'
                      : '当前批次全部实验的聚合指标。'}
                    任务根轮次数：{scoresData.current.taskCount}；P95：
                    {scoresData.current.p95Seconds?.toFixed(2) ?? '—'}s
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
                        {scoresData.current.metrics.map((m: Metric) => {
                          const b = scoresData.baseline?.metrics.find(
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
                              <td>{formatMetric(m)}</td>
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
                  <h3>按 Dataset 拆解</h3>
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
                        {(scoresData.datasets || []).map((ds: Doc) => {
                          const bDs = (scoresData.baselineDatasets || []).find(
                            (x: Doc) => x.dataset === ds.dataset,
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
                            return `${formatMetric(m)}${deltaStr} (n=${m.samples})`;
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
                </>
              )}
            </>
          ) : view === 'agents' ? (
            <>
              <div className="eval-table">
                <table>
                  <thead>
                    <tr>
                      <th>被测组件 / 执行链</th>
                      <th>计划检查点</th>
                      <th>实际执行</th>
                      <th>通过</th>
                      <th>不通过</th>
                      <th>异常</th>
                      <th>未执行</th>
                      <th>未知</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batch.components.map((c: Doc) => (
                      <tr key={c.id}>
                        <td>{c.id}</td>
                        <td>{c.planned}</td>
                        <td>{c.executed}</td>
                        <td>{c.pass}</td>
                        <td>{c.fail}</td>
                        <td>{c.error}</td>
                        <td>{c.not_run}</td>
                        <td>{c.unknown}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                未列出的组件尚无独立评测覆盖。答疑执行链结果不能直接当成导师或生产审核的独立准确率。
              </p>
              <h3>实际模型调用（含重试与备用）</h3>
              {!batch.runtime.length ? (
                <p className="notice">
                  本批次未采集组件调用明细，不能推算内部Agent效果、Token或成本。
                </p>
              ) : (
                <div className="eval-table">
                  <table>
                    <thead>
                      <tr>
                        <th>模型组件</th>
                        <th>调用</th>
                        <th>异常</th>
                        <th>总耗时</th>
                        <th>输入Token</th>
                        <th>输出Token</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batch.runtime.map((c: Doc) => (
                        <tr key={c.id}>
                          <td>{c.id}</td>
                          <td>{c.calls}</td>
                          <td>{c.errors}</td>
                          <td>{c.durationMs}ms</td>
                          <td>{c.tokensIn ?? '未知'}</td>
                          <td>{c.tokensOut ?? '未知'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="eval-toolbar eval-filters">
                <label>
                  Dataset
                  <select
                    value={dataset}
                    onChange={(e) => setDataset(e.target.value)}
                  >
                    <option value="">全部集合</option>
                    {batch.experiments.map((e: Doc) => (
                      <option key={e.id} value={e.id}>
                        {e.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  组件
                  <select
                    value={component}
                    onChange={(e) => setComponent(e.target.value)}
                  >
                    <option value="">全部组件</option>
                    {batch.components.map((c: Doc) => (
                      <option key={c.id}>{c.id}</option>
                    ))}
                  </select>
                </label>
                <label>
                  搜索用例
                  <span className="search-field">
                    <IconSearch />
                    <input
                      value={search}
                      placeholder="用例 ID"
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </span>
                </label>
                <label>
                  评测状态
                  <select
                    value={status}
                    onChange={(e) => {
                      setStatus(e.target.value);
                      if (e.target.value === 'pass') setView('all');
                    }}
                  >
                    <option value="">全部状态</option>
                    {Object.entries(statusLabels).map(([s, label]) => (
                      <option key={s} value={s}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <span>当前 {rows.length} 条</span>
              </div>
              <div className="eval-table eval-case-table">
                <table>
                  <thead>
                    <tr>
                      <th>用例</th>
                      <th>状态</th>
                      <th>首个失败检查点</th>
                      <th>未达标维度</th>
                      <th className="right-cell">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c: Doc) => (
                      <tr
                        key={c.id}
                        className={
                          item?.id === c.id ? 'selected-row' : undefined
                        }
                      >
                        <td>
                          {c.caseId}
                          <br />
                          <small>
                            {c.calibration ? '裁判校准' : '应用回归'} ·{' '}
                            {c.components.join(', ')}
                          </small>
                        </td>
                        <td>{statusLabels[c.status]}</td>
                        <td>{c.firstFailure || '—'}</td>
                        <td>
                          {c.snapshotCurrent
                            ? c.failedDimensions.join(', ') || '—'
                            : '汇总已更新，请查看当前证据'}
                        </td>
                        <td className="right-cell">
                          <button
                            className="secondary btn-sm"
                            onClick={() => setItem(c)}
                          >
                            <IconEye size={14} />
                            查看详情
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="eval-mobile-cases">
                {rows.map((c: Doc) => (
                  <article key={c.id}>
                    <strong>{c.caseId}</strong>
                    <p>
                      {statusLabels[c.status]} ·{' '}
                      {c.firstFailure || '未定位检查点'}
                    </p>
                    <div className="page-actions">
                      <button
                        className="secondary btn-sm"
                        onClick={() => setItem(c)}
                      >
                        <IconEye size={14} />
                        查看详情
                      </button>
                    </div>
                  </article>
                ))}
              </div>
              {!rows.length && <p>当前筛选下没有用例。</p>}
            </>
          )}
          {data.comparison && (
            <section>
              <h3>与基线逐例比较</h3>
              {!data.comparison.comparable ? (
                <p className="notice">{data.comparison.reason}</p>
              ) : (
                <>
                  {['regression', 'fixed', 'incomplete', 'unchanged'].map(
                    (k) => (
                      <span className="badge" key={k}>
                        {
                          (
                            {
                              regression: '新增失败',
                              fixed: '已修复',
                              incomplete: '结果不完整',
                              unchanged: '未变化',
                            } as Doc
                          )[k]
                        }
                        ：
                        {
                          data.comparison.changes.filter(
                            (c: Doc) => c.change === k,
                          ).length
                        }{' '}
                      </span>
                    ),
                  )}
                  {data.comparison.changes
                    .filter((c: Doc) => c.change !== 'unchanged')
                    .map((c: Doc) => (
                      <p key={c.id}>
                        {c.caseId}：{statusLabels[c.before]} →{' '}
                        {statusLabels[c.after]}
                      </p>
                    ))}
                </>
              )}
            </section>
          )}
          <DebugDrawer
            open={!!item}
            onClose={() => setItem(null)}
            wide
            title={
              item
                ? `${item.caseId} · ${statusLabels[item.status]}`
                : '用例详情'
            }
            ariaLabel="用例执行证据"
          >
            {item && (
              <CaseEvidence
                key={`${run}:${item.id}`}
                run={run}
                item={item}
                days={days}
              />
            )}
          </DebugDrawer>
          <p>
            <a
              href={data.links['Human Review']}
              target="_blank"
              rel="noreferrer"
            >
              在 Langfuse 进行人工复核 ↗
            </a>{' '}
            · 复核结论独立保留，不覆盖自动评分。
          </p>
        </>
      )}
    </section>
  );
}
function CaseEvidence({
  run,
  item,
  days,
}: {
  run: string;
  item: Doc;
  days: number;
}) {
  const [data, setData] = useState<Doc | null>(null),
    [error, setError] = useState(''),
    [tab, setTab] = useState<'workflow' | 'checks'>('workflow');
  useEffect(() => {
    const abort = new AbortController();
    setData(null);
    setError('');
    read(
      `evidence?${new URLSearchParams({ run, item: item.id, days: String(days) })}`,
      abort.signal,
    )
      .then((d) => {
        setData(d);
        const hasReplay = d.observations?.some(
          (o: Doc) => o.output?.schema_version === 'duxue-execution.v1',
        );
        setTab(hasReplay ? 'workflow' : 'checks');
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(e.message);
      });
    return () => abort.abort();
  }, [run, item.id, days]);
  const hasReplay = !!data?.observations?.some(
    (o: Doc) => o.output?.schema_version === 'duxue-execution.v1',
  );
  return (
    <div className="eval-case-drawer" aria-label="用例执行证据">
      <div className="section-head">
        <div>
          <p className="compact-meta">
            用例标注：{item.labelStatus} · 自动裁判未校准，人工复核结论请在
            Langfuse 保留。
          </p>
        </div>
        <div className="page-actions">
          <a
            className="button-link secondary btn-sm"
            href={item.url}
            target="_blank"
            rel="noreferrer"
          >
            在 Langfuse 查看原始执行与评分
            <IconExternalLink size={13} />
          </a>
        </div>
      </div>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {!data && !error && <p role="status">正在读取执行证据…</p>}
      {data && (
        <>
          <div className="eval-header">
            <div className="eval-nav" role="tablist" aria-label="证据视图">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'workflow'}
                className={tab === 'workflow' ? 'active' : ''}
                onClick={() => setTab('workflow')}
              >
                流程回放 (Workflow)
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'checks'}
                className={tab === 'checks' ? 'active' : ''}
                onClick={() => setTab('checks')}
              >
                检查点证据 ({item.checks.length})
              </button>
            </div>
            <span className="badge badge-neutral">
              {hasReplay ? '支持节点级回放' : '无节点级拓扑证据'}
            </span>
          </div>
          {tab === 'workflow' ? (
            <WorkflowExecution
              observations={data.observations}
              components={item.components}
            />
          ) : (
            <>
              {item.checks.map((c: Doc) => {
                const obs = data.observations.find(
                  (o: Doc) => o.id === c.observation_id,
                );
                const observed = obs?.output?.evaluation?.observed;
                return (
                  <details key={c.check_id} open={c.status !== 'pass'}>
                    <summary>
                      {c.check_id} · {statusLabels[c.status]} · {c.component}
                    </summary>
                    {observed?.reason && (
                      <p className="notice">
                        执行原因：{observed.reason} · 最终交付：
                        {observed.outcome}
                      </p>
                    )}
                    <h4>实际交付</h4>
                    <pre>
                      {pretty(
                        obs?.output?.response ||
                          c.response ||
                          '未执行或证据缺失',
                      )}
                    </pre>
                    <h4>本次固定要求与阈值</h4>
                    <pre>{pretty(c.requirement)}</pre>
                    <h4>当前原生评分与理由</h4>
                    {checkpointGrades(c, data.scores).map((s: Doc) => (
                      <details key={s.name} open>
                        <summary>
                          {statusLabels[s.status]} · {s.name} ={' '}
                          {String(s.value)}
                          ；要求 {s.threshold}
                        </summary>
                        <p>{s.comment || '裁判未提供理由'}</p>
                        {s.metadata?.grades && (
                          <pre>{pretty(s.metadata.grades)}</pre>
                        )}
                      </details>
                    ))}
                    {observed && (
                      <details>
                        <summary>候选、门禁及工具证据</summary>
                        <pre>{pretty(observed)}</pre>
                      </details>
                    )}
                  </details>
                );
              })}
              <section>
                <h4>人工复核记录</h4>
                {data.scores.filter(
                  (s: Doc) =>
                    s.name === 'review.disposition' &&
                    s.source === 'ANNOTATION',
                ).length ? (
                  data.scores
                    .filter(
                      (s: Doc) =>
                        s.name === 'review.disposition' &&
                        s.source === 'ANNOTATION',
                    )
                    .map((s: Doc) => (
                      <p key={s.id}>
                        {String(s.value)} · 对象 {s.subject?.id} ·{' '}
                        {s.comment || '未提供理由'}
                      </p>
                    ))
                ) : (
                  <p className="muted">尚无人工复核结论，自动失败仍待复核。</p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
