'use client';
import { useEffect, useState } from 'react';
import { WorkflowExplorer } from './inventory';
import {
  IconArrowLeft,
  IconArrowRight,
  IconExternalLink,
  IconPause,
  IconPlay,
  IconRollback,
} from './icons';
type Doc = Record<string, any>;
export function WorkflowExecution({
  observations,
  components = [],
}: {
  observations: Doc[];
  components?: string[];
}) {
  const executions = observations.filter(
    (o) => o.output?.schema_version === 'duxue-execution.v1',
  );
  const [selected, setSelected] = useState(''),
    [flow, setFlow] = useState(''),
    [replayIndex, setReplayIndex] = useState<number | null>(null),
    [playing, setPlaying] = useState(false);
  const current = executions.find((o) => o.id === selected) || executions[0];
  const catalog = current?.output?.catalog;
  const events: Doc[] = current?.output?.events || [];
  const ids = Object.keys(catalog?.workflows || {});
  const activeEvent =
    replayIndex !== null && events[replayIndex] ? events[replayIndex] : null;
  const visibleEvents =
    replayIndex !== null ? events.slice(0, replayIndex + 1) : events;
  const active =
    activeEvent?.workflow_id && ids.includes(activeEvent.workflow_id)
      ? activeEvent.workflow_id
      : ids.includes(flow)
        ? flow
        : ids[0];
  useEffect(() => {
    setReplayIndex(null);
    setPlaying(false);
  }, [current?.id]);
  useEffect(() => {
    if (!playing || !events.length) return;
    const timer = setInterval(() => {
      setReplayIndex((prev) => {
        const next = prev === null ? 0 : prev + 1;
        if (next >= events.length) {
          setPlaying(false);
          return events.length - 1;
        }
        return next;
      });
    }, 1100);
    return () => clearInterval(timer);
  }, [playing, events.length]);
  return (
    <section aria-label="Workflow历史执行">
      <div className="section-head">
        <div>
          <h3>Workflow 执行回放</h3>
          <p className="compact-meta">
            使用执行时冻结的拓扑。绿色/红色高亮为已执行节点，橙色为当前回放步骤，灰色为未经过节点。
          </p>
        </div>
        {active && (
          <div className="page-actions">
            <a
              className="button-link secondary btn-sm"
              href={`/workflows/${encodeURIComponent(active)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              在 Workflow 中查看当前定义
              <IconExternalLink size={13} />
            </a>
          </div>
        )}
      </div>
      {!current ? (
        <div className="notice">
          <p style={{ margin: 0 }}>
            这次历史执行没有记录节点级证据，无法还原流程图。原始 Trace
            和检查点证据仍可查看；不会套用当前配置补画历史路径。
          </p>
          {!!components.length && (
            <div className="page-actions" style={{ marginTop: 10 }}>
              {components.map((id) => (
                <a
                  key={id}
                  className="button-link secondary btn-sm"
                  href={`/agents/${encodeURIComponent(id)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  查看组件：{id}
                  <IconExternalLink size={13} />
                </a>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="eval-toolbar">
            <div className="eval-filters">
              <label>
                执行片段
                <select
                  value={current.id}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {executions.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.metadata?.check_id || o.name} · {o.id}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                执行时的 Workflow
                <select
                  value={active || ''}
                  onChange={(e) => {
                    setPlaying(false);
                    setReplayIndex(null);
                    setFlow(e.target.value);
                  }}
                >
                  {ids.map((id) => (
                    <option key={id}>{id}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          {!!events.length && (
            <div className="replay-bar" aria-label="流程回放控制">
              <div className="replay-status">
                <span className="badge">
                  {replayIndex === null
                    ? `全部 ${events.length} 步`
                    : `步骤 ${replayIndex + 1} / ${events.length}`}
                </span>
                {activeEvent ? (
                  <span className="compact-meta">
                    {activeEvent.workflow_id} ·{' '}
                    {activeEvent.node_id ||
                      `${activeEvent.from} → ${activeEvent.to}`}{' '}
                    · {activeEvent.status}
                  </span>
                ) : (
                  <span className="compact-meta">
                    点击“单步回放”或下方步骤节点，按顺序重现执行路径与输入输出。
                  </span>
                )}
              </div>
              <div className="page-actions">
                <button
                  className="secondary btn-sm"
                  disabled={replayIndex !== null && replayIndex <= 0}
                  onClick={() => {
                    setPlaying(false);
                    setReplayIndex((prev) =>
                      prev === null ? 0 : Math.max(0, prev - 1),
                    );
                  }}
                >
                  <IconArrowLeft size={14} />
                  上一步
                </button>
                <button
                  className="btn-sm"
                  onClick={() => {
                    if (playing) {
                      setPlaying(false);
                      return;
                    }
                    if (
                      replayIndex === null ||
                      replayIndex >= events.length - 1
                    )
                      setReplayIndex(0);
                    setPlaying(true);
                  }}
                >
                  {playing ? <IconPause size={14} /> : <IconPlay size={14} />}
                  {playing
                    ? '暂停'
                    : replayIndex === null
                      ? '播放回放'
                      : '继续'}
                </button>
                <button
                  className="secondary btn-sm"
                  disabled={
                    replayIndex !== null && replayIndex >= events.length - 1
                  }
                  onClick={() => {
                    setPlaying(false);
                    setReplayIndex((prev) =>
                      prev === null ? 0 : Math.min(events.length - 1, prev + 1),
                    );
                  }}
                >
                  下一步
                  <IconArrowRight size={14} />
                </button>
                {replayIndex !== null && (
                  <button
                    className="secondary btn-sm"
                    onClick={() => {
                      setPlaying(false);
                      setReplayIndex(null);
                    }}
                  >
                    <IconRollback size={14} />
                    查看全部
                  </button>
                )}
              </div>
            </div>
          )}
          {!!events.length && (
            <div className="replay-steps" aria-label="执行步骤时间轴">
              {events.map((e: Doc, index: number) => (
                <button
                  key={e.id}
                  type="button"
                  className={
                    'replay-step ' +
                    (replayIndex === index
                      ? 'current'
                      : e.status === 'failed'
                        ? 'failed'
                        : '')
                  }
                  onClick={() => {
                    setPlaying(false);
                    setReplayIndex(index);
                  }}
                >
                  #{index + 1} {e.node_id || `${e.from}→${e.to}`}
                </button>
              ))}
            </div>
          )}
          {active ? (
            <WorkflowExplorer
              key={`${current.id}:${active}`}
              catalog={catalog}
              initialWorkflow={active}
              execution={visibleEvents}
              activeEvent={activeEvent}
              navigate={(url) =>
                window.open(url, '_blank', 'noopener,noreferrer')
              }
            />
          ) : (
            <p>执行记录未包含可映射的Workflow节点，见下方原始事件。</p>
          )}
          <details>
            <summary>按执行顺序查看节点、分支与重复尝试</summary>
            {events.map((e: Doc) => (
              <details key={e.id}>
                <summary>
                  #{e.id} · {e.workflow_id} ·{' '}
                  {e.node_id || `${e.from} → ${e.to}`} · {e.status}
                </summary>
                <pre>{JSON.stringify(e, null, 2)}</pre>
              </details>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
export function TraceExecutionLookup() {
  const [trace, setTrace] = useState(''),
    [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<Doc | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  async function load() {
    setLoading(true);
    setError('');
    setData(null);
    try {
      const r = await fetch(
        `/api/evaluation/trace?${new URLSearchParams({ trace, date })}`,
      );
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '读取失败');
      setData(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="eval-case-detail">
      <div className="section-head">
        <div>
          <h3>查看一次线上执行</h3>
        </div>
      </div>
      <div className="eval-toolbar">
        <div className="eval-filters">
          <label>
            Trace ID
            <input value={trace} onChange={(e) => setTrace(e.target.value)} />
          </label>
          <label>
            执行日期（UTC）
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        </div>
        <div className="page-actions">
          <button disabled={loading} onClick={load}>
            <IconPlay size={14} />
            {loading ? '读取中…' : '查看执行链路'}
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {data && <WorkflowExecution observations={data.observations} />}
    </section>
  );
}
