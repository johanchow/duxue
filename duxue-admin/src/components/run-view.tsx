'use client';
type Doc = Record<string, any>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export function RunView({ result }: { result: Doc }) {
  return (
    <div className="run-result">
      <div className="section-head">
        <h3>
          {result.mode === 'agent' || result.mode === 'component'
            ? 'Agent 调试输出'
            : 'Workflow 执行输出'}
        </h3>
        <span className="badge">
          {result.status} · {result.model_requests} 次模型调用 ·{' '}
          {result.duration_ms}ms
        </span>
      </div>
      <div className="final-output">{result.content}</div>
      {result.failure && (
        <p className="notice error">失败原因：{result.failure}</p>
      )}
      {result.source && (
        <p>
          来源：{result.source.kind === 'draft' ? '已保存草稿' : '已发布配置'} ·
          快照 {result.digest}
        </p>
      )}
      {result.output && (
        <details>
          <summary>结构化最终输出</summary>
          <pre>{pretty(result.output)}</pre>
        </details>
      )}
      {result.visual && (
        <details>
          <summary>通过校验的配图</summary>
          <pre>{pretty(result.visual)}</pre>
        </details>
      )}
      {result.sandbox_effects && (
        <details>
          <summary>隔离状态写入结果（未写入业务数据库）</summary>
          <pre>{pretty(result.sandbox_effects)}</pre>
        </details>
      )}
      {!!result.events?.length && (
        <>
          <h3>Node / Edge 执行记录</h3>
          {result.events.map((event: Doc) => (
            <details key={event.id}>
              <summary>
                {event.id}. {event.workflow_id ? event.workflow_id + ' · ' : ''}
                {event.node_id ||
                  event.unit_id ||
                  `${event.from} → ${event.to}`}{' '}
                · {event.kind} · {event.status}
                {event.kind === 'edge'
                  ? event.selected
                    ? ' · 已选择'
                    : ' · 未选择'
                  : ''}
              </summary>
              <pre>{pretty(event)}</pre>
            </details>
          ))}
        </>
      )}
      <h3>模型调用记录</h3>
      {result.steps?.map((step: Doc, index: number) => (
        <details key={index}>
          <summary>
            {index + 1}. {step.component} · {step.model} · {step.status} ·{' '}
            {step.duration_ms}ms
          </summary>
          <h4>实际输入</h4>
          <pre>{pretty(step.input)}</pre>
          <h4>校验后输出／错误</h4>
          <pre>{pretty(step.output ?? step.error)}</pre>
          {step.raw_output && (
            <details>
              <summary>提供商原始输出</summary>
              <pre>{pretty(step.raw_output)}</pre>
            </details>
          )}
          <p>
            {step.tokens_in ?? '未知'} 输入 Token · {step.tokens_out ?? '未知'}{' '}
            输出 Token
          </p>
        </details>
      ))}
      {result.executor_digest && (
        <details>
          <summary>执行代码摘要</summary>
          <code>{result.executor_digest}</code>
          <p>同一输入与配置仍可能因模型随机性产生不同结果。</p>
        </details>
      )}
    </div>
  );
}
