'use client';
import { useState } from 'react';
import { RunView } from './run-view';
import { IconPlay, IconWorkflow } from './icons';
type Doc = Record<string, any>;
import { debugCapability, type DebugTarget } from '../lib/debug-capability';
export type { DebugTarget } from '../lib/debug-capability';
export function DebugPanel({
  snapshot,
  source,
  target,
  capabilities,
  dirty = false,
  onComplete,
  onResult,
  onInspect,
  navigate,
}: {
  snapshot: Doc;
  source: 'release' | 'draft';
  target: DebugTarget;
  capabilities: Doc;
  dirty?: boolean;
  onComplete: () => Promise<unknown>;
  onResult?: (result: Doc) => void;
  onInspect?: () => void;
  navigate?: (url: string) => void;
}) {
  const definition = Object.values(snapshot.bundle.files).find(
    (item: any) => item.id === target.id,
  ) as Doc | undefined;
  const models: Doc[] = target.kind === 'agent' ? definition?.models || [] : [];
  const initial =
    definition?.prompt?.delivery === 'user'
      ? JSON.stringify(
          Object.fromEntries(
            Object.entries(definition.prompt.variables).map(
              ([key, value]: any) => [
                key,
                value.type === 'array' ? [] : value.type === 'object' ? {} : '',
              ],
            ),
          ),
          null,
          2,
        )
      : '请解释植物细胞和动物细胞的主要区别。';
  const [content, setContent] = useState(initial),
    [problem, setProblem] = useState(''),
    [context, setContext] = useState('{}'),
    [model, setModel] = useState(models[0]?.component_id || ''),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [result, setResult] = useState<Doc | null>(null);
  const capability = debugCapability(target, snapshot.bundle, capabilities);
  const supported = capability.supported;
  async function run() {
    if (dirty || busy) return;
    setBusy(true);
    setMessage('正在执行真实隔离调试…');
    setResult(null);
    try {
      const parsed = JSON.parse(context);
      const response = await fetch(
        `/api/${source === 'draft' ? 'drafts' : 'releases'}/${snapshot.id}/debug`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            revision: snapshot.revision,
            input: {
              target_kind: target.kind,
              target_id: target.id,
              ...(model ? { component_id: model } : {}),
              content,
              problem,
              context: parsed,
            },
          }),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '调试失败');
      setResult(data);
      onResult?.(data);
      await onComplete();
      setMessage(
        '调试已记录 · ' +
          ({ succeeded: '通过', failed: '失败', blocked: '已拦截' }[
            data.status as string
          ] || data.status),
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="debug" aria-label="目标调试">
      <div className="section-head">
        <h2>
          {target.kind === 'workflow' ? 'Workflow' : 'Agent'} 调试 · {target.id}
        </h2>
        <span className="badge">
          {source === 'draft' ? '已保存草稿' : '已发布配置'}
        </span>
      </div>
      <p>
        本次使用
        {source === 'draft'
          ? `草稿修订 ${snapshot.revision}`
          : `发布 R${snapshot.sequence}`}
        的完整配置快照；运行期间固定全部组件配置。
      </p>
      {!supported ? (
        <div className="notice">
          <p>{capability.reason}</p>
          {capability.workflowId && navigate && (
            <div className="page-actions">
              <button
                className="secondary"
                onClick={() => navigate(`/workflows/${capability.workflowId}`)}
              >
                <IconWorkflow />
                打开所属 Workflow
              </button>
            </div>
          )}
        </div>
      ) : (
        <>
          {models.length > 1 && (
            <label>
              执行模型
              <select
                aria-label="执行模型"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {models.map((item) => (
                  <option key={item.component_id} value={item.component_id}>
                    {item.component_id}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {definition?.prompt?.delivery === 'user'
              ? '模板变量 JSON'
              : '调试输入'}
            <textarea
              aria-label="调试输入"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </label>
          {((target.kind === 'workflow' &&
            ['tutoring', 'reflection'].includes(target.id)) ||
            capabilities.code_agents?.[target.id]) && (
            <>
              {(target.id === 'tutoring' ||
                target.id === 'tutoring.session-turn') && (
                <label>
                  受保护题目（可选）
                  <textarea
                    aria-label="受保护题目"
                    value={problem}
                    onChange={(e) => setProblem(e.target.value)}
                  />
                </label>
              )}
              <details>
                <summary>初始上下文与历史（JSON）</summary>
                <textarea
                  aria-label="调试上下文"
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                />
                <p>
                  只使用输入的测试状态，不读取真实孩子数据。Tutoring支持文字历史、任务标题、题目状态与尝试证据；Reflection使用review_date、review_feeling、review_reflection。当前不支持图片附件。
                </p>
                <pre>
                  {JSON.stringify(capabilities.context_schema, null, 2)}
                </pre>
              </details>
            </>
          )}
          {dirty && <p className="notice">请先保存修改，再调试已保存草稿。</p>}
          <div className="page-actions">
            <button disabled={busy || dirty || !content.trim()} onClick={run}>
              <IconPlay />
              {busy ? '运行中…' : '运行真实调试'}
            </button>
          </div>
          <p className="muted">
            调试不会修改实际学习数据，会产生真实模型调用用量。
          </p>
        </>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {result && (
        <>
          {onInspect && (
            <div className="page-actions">
              <button className="secondary" onClick={onInspect}>
                <IconWorkflow />
                查看流程执行
              </button>
            </div>
          )}
          <RunView result={result} />
        </>
      )}
    </section>
  );
}
