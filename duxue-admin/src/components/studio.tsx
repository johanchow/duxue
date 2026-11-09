'use client';
import { useEffect, useState } from 'react';
import {
  AgentInventory,
  AgentDetail,
  WorkflowInventory,
  WorkflowExplorer,
} from './inventory';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { studioRoute, studioPaths } from '../lib/studio-route';
import { LoadStatus, VersionDetail } from './versions';
import { runTarget } from '../lib/run-target';
import { RunView } from './run-view';
import { DebugPanel, type DebugTarget } from './debug-panel';
import { DebugDrawer } from './debug-drawer';
import { debugCapability } from '../lib/debug-capability';

type Doc = Record<string, any>;
async function api(path: string, method = 'GET', body?: unknown) {
  const response = await fetch('/api/' + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
const labels: Record<string, string> = {
  succeeded: '通过',
  blocked: '已拦截',
  failed: '失败',
  running: '运行中',
  interrupted: '结果未知',
  loaded: '已加载',
};
const pretty = (x: unknown) => JSON.stringify(x, null, 2);
const time = (x: string) =>
  new Date(x).toLocaleString('zh-CN', { hour12: false });
export default function Studio() {
  const [state, setState] = useState<Doc | null>(null),
    [logged, setLogged] = useState<boolean | null>(null);
  const router = useRouter(),
    pathname = usePathname(),
    search = useSearchParams();
  const { tab, id: entityId } = studioRoute(pathname);
  const agent =
    tab === 'agent-detail'
      ? (state?.catalog?.components || state?.catalog?.agents)?.find(
          (item: Doc) => item.id === entityId,
        )
      : null;
  const draftId =
    tab === 'config'
      ? entityId
      : ['agent-detail', 'flow-detail'].includes(tab)
        ? search.get('draft')
        : null;
  function navigate(url: string) {
    if (dirty && !window.confirm('当前配置尚未保存，确定离开？')) return;
    setDirty(false);
    setMessage('');
    router.push(url);
  }
  function setTab(next: string) {
    navigate(studioPaths[next] || '/');
  }
  const [email, setEmail] = useState(''),
    [password, setPassword] = useState(''),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Doc | null>(null),
    [original, setOriginal] = useState<Doc | null>(null),
    [file, setFile] = useState('agents/tutoring.turn.json'),
    [dirty, setDirty] = useState(false);
  const [run, setRun] = useState<Doc | null>(null),
    [showContract, setShowContract] = useState(false);
  const [packageTarget, setPackageTarget] = useState<DebugTarget>({
    kind: 'workflow',
    id: 'tutoring',
  });
  const [workflowRun, setWorkflowRun] = useState<Doc | null>(null);
  const [specificVersion, setSpecificVersion] = useState<Doc | null>(null);
  const [publishedDebug, setPublishedDebug] = useState<Doc | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);
  const graphSnapshot = draftId ? draft : publishedDebug;
  const canEdit = state?.user.role === 'admin';
  useEffect(() => {
    setPublishedDebug(null);
    setRun(null);
    setWorkflowRun(null);
    setDebugOpen(false);
  }, [entityId, tab, draftId]);
  async function refresh() {
    const data = await api('state');
    setState(data);
    setLogged(true);
    return data;
  }
  useEffect(() => {
    api('session')
      .then(() => refresh())
      .catch(() => setLogged(false));
  }, []);
  useEffect(() => {
    if (!logged) return;
    const id = setInterval(() => {
      api('state')
        .then(setState)
        .catch(() => {});
    }, 15000);
    return () => clearInterval(id);
  }, [logged]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setMessage('');
    try {
      await work();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openDraft(id: string, agentId?: string) {
    navigate(
      agentId
        ? `/agents/${encodeURIComponent(agentId)}?draft=${id}`
        : `/drafts/${id}`,
    );
  }
  useEffect(() => {
    if (!logged) return;
    if (!draftId) {
      setDraft(null);
      setOriginal(null);
      return;
    }
    let cancelled = false;
    setDraft(null);
    api('drafts/' + encodeURIComponent(draftId))
      .then((d) => {
        if (cancelled) return;
        if (d.bundle.format_version !== 3) {
          setMessage('配置格式无效，请重新创建待发布修改。');
          return;
        }
        if (d.state !== 'working') {
          setMessage('此修改已发布或归档，请在Agent详情打开当前待发布配置。');
          return;
        }
        setDraft(d);
        setOriginal(structuredClone(d.base_bundle || d.bundle));
        setFile(
          agent?.file || search.get('file') || 'agents/tutoring.turn.json',
        );
        setDirty(false);
        setRun(null);
      })
      .catch((error) => {
        if (!cancelled) setMessage(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [logged, draftId, agent?.file]);
  useEffect(() => {
    if (!logged || tab !== 'release-detail' || !entityId) return;
    let cancelled = false;
    setSpecificVersion(null);
    api('releases/' + entityId + '/detail')
      .then((value) => {
        if (!cancelled) setSpecificVersion(value);
      })
      .catch((error) => {
        if (!cancelled) setMessage(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [logged, tab, entityId]);
  useEffect(() => {
    if (draft && location.hash === '#debug') setDebugOpen(true);
    if (draft && location.hash === '#changes')
      document.getElementById('changes')?.scrollIntoView();
  }, [draft?.id]);
  useEffect(() => {
    if (!dirty) return;
    function warn(event: BeforeUnloadEvent) {
      event.preventDefault();
    }
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  function edit(next: Doc) {
    if (!canEdit) return;
    setDraft({
      ...draft!,
      bundle: {
        ...draft!.bundle,
        files: { ...draft!.bundle.files, [file]: next },
      },
    });
    setDirty(true);
  }
  async function openPublishedDebug() {
    if (publishedDebug?.id === state?.environment.release_id) {
      setDebugOpen(true);
      return;
    }
    setWorkflowRun(null);
    setPublishedDebug(null);
    setDebugOpen(true);
    await action(async () => {
      setPublishedDebug(
        await api('releases/' + state!.environment.release_id + '/detail'),
      );
    });
  }
  function inspectWorkflow() {
    setDebugOpen(false);
    requestAnimationFrame(() =>
      document
        .querySelector('.workflow-canvas')
        ?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
    );
  }
  async function save() {
    const next = await api('drafts/' + draft!.id, 'PUT', {
      revision: draft!.revision,
      title: draft!.title,
      bundle: draft!.bundle,
    });
    setDraft(next);
    setDirty(false);
    await refresh();
    setMessage('草稿已保存，旧校验与调试结果已失效。');
  }
  if (logged === null)
    return <div className="loading">正在连接 Agent Studio…</div>;
  if (!logged)
    return (
      <main className="login">
        <div className="brand">
          读学 <span>AGENT STUDIO</span>
        </div>
        <h1>
          让每次调整
          <br />
          都有据可循。
        </h1>
        <p>登录 Agent 配置管理台</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              await api('session', 'POST', { email, password });
              setPassword('');
              await refresh();
            });
          }}
        >
          <label>
            管理员邮箱
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <button disabled={busy}>登录管理台 →</button>
        </form>
        {message && (
          <div role="alert" className="notice error">
            {message}
          </div>
        )}
        <small>独立账号登录</small>
      </main>
    );
  const nav = [
    ['flows', '⌘', 'Workflow'],
    ['agents', '◉', 'Agent'],
    ['releases', '↥', '发布管理'],
    ['runs', '◷', '调试记录'],
  ];
  const heading =
    tab === 'agent-detail'
      ? agent?.name || 'Agent 详情'
      : tab === 'flow-detail'
        ? entityId
        : tab === 'release-detail'
          ? `版本 R${specificVersion?.sequence || '…'}`
          : tab === 'config'
            ? '待发布配置'
            : tab === 'missing'
              ? '页面不存在'
              : nav.find((n) => n[0] === tab)?.[2];
  const docs = Object.keys(
      draft?.bundle.files || state?.catalog?.bundle.files || {},
    ).filter((path) =>
      ['agents', 'gates', 'tools'].includes(path.split('/')[0]),
    ),
    doc = draft?.bundle.files[file];
  const release = state?.releases.find(
    (r: Doc) => r.id === state.environment?.release_id,
  );
  const changed =
    draft && original
      ? docs.filter(
          (name) =>
            pretty(original.files[name]) !== pretty(draft.bundle.files[name]),
        )
      : [];
  const agentCapability =
    agent && state?.catalog
      ? debugCapability(
          { kind: 'agent', id: agent.id },
          state.catalog.bundle,
          state.catalog.debug_capabilities || {},
        )
      : null;
  const pending = state?.drafts[0];
  const successful = (state?.runs || []).filter(
    (item: Doc) =>
      pending &&
      item.draft_id === pending.id &&
      item.revision === pending.revision &&
      item.status === 'succeeded' &&
      item.digest === pending.validation?.digest,
  );
  const covered = new Set(
    successful.flatMap((item: Doc) => item.covered_components || []),
  );
  const missing = (pending?.required_components || []).filter(
    (id: string) => !covered.has(id),
  );
  async function rollback(id: string, sequence: string) {
    await api(`releases/${id}/rollback`, 'POST', {
      generation: state!.environment.generation,
    });
    await refresh();
    setMessage(`已切换至R${sequence}，等待加载。`);
  }
  async function editAgent() {
    const current = await api('drafts', 'POST', {});
    await refresh();
    await openDraft(current.id, agent.id);
  }
  async function publish() {
    const result = await api(`drafts/${pending.id}/publish`, 'POST', {
      revision: pending.revision,
      generation: state!.environment.generation,
    });
    await refresh();
    router.push('/releases/' + result.id);
  }
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          读学 <span>AGENT STUDIO</span>
        </div>
        <div className="workspace">
          AGENT WORKSPACE<span>流程 · 配置 · 版本</span>
        </div>
        <nav>
          {nav.map(([id, icon, label]) => (
            <button
              key={id}
              className={
                tab === id ||
                (tab === 'agent-detail' && id === 'agents') ||
                (tab === 'flow-detail' && id === 'flows') ||
                ((tab === 'config' || tab === 'release-detail') &&
                  id === 'releases')
                  ? 'active'
                  : ''
              }
              onClick={() => setTab(id)}
            >
              <i>{icon}</i>
              {label}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          <span className="dot" />{' '}
          {state?.environment.name === 'prod' ? '正式环境' : '测试环境'}
          <p>
            {state?.user.email} · {state?.user.role}
          </p>
          <button
            onClick={() =>
              action(async () => {
                await api('session', 'DELETE');
                setLogged(false);
                setDraft(null);
              })
            }
          >
            退出登录
          </button>
        </div>
      </aside>
      <main>
        <header>
          <span>WORKSPACE / {heading}</span>
          <div>
            <b className="env">
              {state?.environment.name === 'prod' ? 'PROD' : 'TEST'}
            </b>
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await refresh();
                  setMessage('已刷新最新状态');
                })
              }
            >
              刷新
            </button>
          </div>
        </header>
        <div className="page-heading">
          <div>
            <div className="eyebrow">DUXUE · AGENTS</div>
            <h1>{heading}</h1>
          </div>
          {tab === 'agent-detail' && agent && (
            <div className="page-actions">
              <button className="secondary" onClick={() => navigate('/agents')}>
                返回 Agent 列表
              </button>
              {!draftId &&
                state?.environment.release_id &&
                (agentCapability?.supported ? (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={openPublishedDebug}
                  >
                    调试已发布配置
                  </button>
                ) : (
                  <>
                    <span className="badge" title={agentCapability?.reason}>
                      未开放独立调试
                    </span>
                    {agentCapability?.workflowId && (
                      <button
                        className="secondary"
                        onClick={() =>
                          navigate(`/workflows/${agentCapability.workflowId}`)
                        }
                      >
                        打开所属 Workflow
                      </button>
                    )}
                  </>
                ))}
              {draftId && draft && agentCapability?.supported && (
                <button
                  className="secondary"
                  onClick={() => setDebugOpen(true)}
                >
                  调试已保存草稿
                </button>
              )}
              {!draftId && canEdit && (
                <button disabled={busy} onClick={() => action(editAgent)}>
                  编辑配置
                </button>
              )}
            </div>
          )}
        </div>
        {message && (
          <div role="status" className="notice">
            {message}
          </div>
        )}
        {state?.catalogError && (
          <div className="notice error">
            配置目录暂不可用：{state.catalogError}
          </div>
        )}
        {tab === 'agent-detail' &&
          agentCapability &&
          !agentCapability.supported && (
            <p className="notice">{agentCapability.reason}</p>
          )}
        {tab === 'agent-detail' && agent && state?.catalog && (
          <AgentDetail
            catalog={state.catalog}
            agent={agent}
            navigate={navigate}
            editing={!!draftId && agent.editable}
            hasChanges={!!pending?.changed_ids.includes(agent.id)}
          />
        )}
        {tab === 'config' && !draftId && (
          <section>
            <h2>完整配置包的草稿</h2>
            <p>
              Agent 详情负责查看和编辑单个
              Agent；这里统一管理尚未发布的完整配置包，集中校验、调试和发布，保证导师、Judge与工具版本一致。
            </p>
          </section>
        )}
        {(tab === 'config' ||
          (tab === 'agent-detail' && agent?.editable && draftId)) &&
          (!draft ? (
            draftId ? (
              <section>
                <p>{message || '正在加载配置草稿…'}</p>
              </section>
            ) : (
              <DraftList
                state={state}
                open={(id) => action(() => openDraft(id))}
              />
            )
          ) : (
            <>
              <div className="toolbar">
                <div>
                  <b>当前待发布配置</b>
                  <span className="badge">未发布</span>
                  {dirty && <span className="unsaved">未保存</span>}
                </div>
                <div className="page-actions">
                  {tab === 'agent-detail' && (
                    <button
                      className="secondary"
                      onClick={() => navigate(`/drafts/${draft.id}`)}
                    >
                      完整配置包
                    </button>
                  )}
                  {tab === 'config' && (
                    <button
                      className="secondary"
                      onClick={() => setDebugOpen(true)}
                    >
                      调试已保存草稿
                    </button>
                  )}
                  {canEdit && (
                    <>
                      <button
                        className="secondary"
                        disabled={busy || !dirty}
                        onClick={() => action(save)}
                      >
                        保存草稿
                      </button>
                      <button
                        className="secondary"
                        disabled={busy || dirty}
                        onClick={() =>
                          action(async () => {
                            const v = await api(
                              `drafts/${draft.id}/validate`,
                              'POST',
                              { revision: draft.revision },
                            );
                            setDraft({ ...draft, validation: v });
                            setMessage(
                              '配置校验通过 · ' + v.digest.slice(0, 12),
                            );
                          })
                        }
                      >
                        校验配置
                      </button>
                      <button
                        disabled={busy || dirty}
                        onClick={() => navigate('/releases')}
                      >
                        前往发布管理
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div
                className={
                  tab === 'agent-detail'
                    ? 'editor-grid single-editor'
                    : 'editor-grid'
                }
              >
                {tab !== 'agent-detail' && (
                  <div className="file-list">
                    {docs.map((name) => (
                      <button
                        key={name}
                        className={name === file ? 'selected' : ''}
                        onClick={() => setFile(name)}
                      >
                        <span>
                          {name.startsWith('agents')
                            ? 'AGENT'
                            : name.startsWith('gates')
                              ? 'JUDGE'
                              : 'TOOL'}
                        </span>
                        {name.split('/')[1].replace('.json', '')}
                      </button>
                    ))}
                  </div>
                )}
                <section className="editor">
                  <div className="section-head">
                    <h2>{doc?.id}</h2>
                    {changed.includes(file) && (
                      <span className="badge">有待发布修改</span>
                    )}
                  </div>
                  {canEdit ? (
                    <>
                      <h3>显示信息</h3>
                      <label>
                        显示名称
                        <input
                          value={doc?.display_name || ''}
                          onChange={(event) =>
                            edit({ ...doc, display_name: event.target.value })
                          }
                          placeholder={agent?.name || doc?.id}
                        />
                      </label>
                      <label>
                        简介
                        <textarea
                          value={doc?.description || ''}
                          onChange={(event) =>
                            edit({ ...doc, description: event.target.value })
                          }
                        />
                      </label>
                      {doc?.models && (
                        <>
                          <h3>模型与预算</h3>
                          {doc.models.map((model: Doc, index: number) => (
                            <div
                              className="model-grid"
                              key={model.component_id}
                            >
                              <label>
                                {index ? '备用模型' : '模型名称'}
                                <input
                                  value={model.name}
                                  onChange={(e) => {
                                    const n = structuredClone(doc);
                                    n.models[index].name = e.target.value;
                                    edit(n);
                                  }}
                                />
                              </label>
                              {[
                                ['temperature', '温度'],
                                ['max_output_tokens', 'Token上限'],
                                ['timeout_ms', '超时(ms)'],
                              ].map(([key, label]) => (
                                <label key={key}>
                                  {label}
                                  <input
                                    type="number"
                                    step={key === 'temperature' ? '0.1' : '1'}
                                    value={model[key]}
                                    onChange={(e) => {
                                      const n = structuredClone(doc);
                                      n.models[index][key] = Number(
                                        e.target.value,
                                      );
                                      edit(n);
                                    }}
                                  />
                                </label>
                              ))}
                            </div>
                          ))}
                          <h3>主 Prompt</h3>
                          <textarea
                            aria-label="主Prompt"
                            className="prompt"
                            value={doc.prompt.template}
                            onChange={(e) =>
                              edit({
                                ...doc,
                                prompt: {
                                  ...doc.prompt,
                                  template: e.target.value,
                                },
                              })
                            }
                          />
                          <h3>
                            具名指令片段{' '}
                            <small>
                              {Object.keys(doc.prompt.fragments || {}).length}项
                            </small>
                          </h3>
                          {Object.entries(doc.prompt.fragments || {}).map(
                            ([name, value]) => (
                              <details key={name}>
                                <summary>
                                  {name}
                                  <small>{(value as Doc).id}</small>
                                </summary>
                                <textarea
                                  aria-label={name}
                                  value={(value as Doc).template}
                                  onChange={(e) => {
                                    const n = structuredClone(doc);
                                    n.prompt.fragments[name].template =
                                      e.target.value;
                                    edit(n);
                                  }}
                                />
                                <code>
                                  变量：
                                  {Object.keys((value as Doc).variables).join(
                                    '、',
                                  ) || '无'}
                                </code>
                              </details>
                            ),
                          )}
                          <h3>已注册工具</h3>
                          <div className="checks">
                            {(
                              state?.catalog?.bundle.files[file]?.tools || []
                            ).map((tool: string) => (
                              <label key={tool}>
                                <input
                                  type="checkbox"
                                  checked={doc.tools.includes(tool)}
                                  onChange={(e) =>
                                    edit({
                                      ...doc,
                                      tools: e.target.checked
                                        ? [...doc.tools, tool]
                                        : doc.tools.filter(
                                            (x: string) => x !== tool,
                                          ),
                                    })
                                  }
                                />
                                {tool}
                              </label>
                            ))}
                            {!doc.tools.length && (
                              <p className="muted">当前未启用工具。</p>
                            )}
                          </div>
                        </>
                      )}
                      {doc?.static_result && (
                        <>
                          <h3>工具静态正文</h3>
                          <textarea
                            className="prompt"
                            aria-label="工具静态正文"
                            value={doc.static_result.guidelines}
                            onChange={(e) =>
                              edit({
                                ...doc,
                                static_result: {
                                  ...doc.static_result,
                                  guidelines: e.target.value,
                                },
                              })
                            }
                          />
                        </>
                      )}
                    </>
                  ) : (
                    <pre>{pretty(doc)}</pre>
                  )}
                  <div className="page-actions">
                    <button
                      className="text-button"
                      onClick={() => setShowContract(!showContract)}
                    >
                      {showContract ? '收起' : '查看'}只读契约与完整定义
                    </button>
                  </div>
                  {showContract && (
                    <>
                      <h4>输入契约</h4>
                      <pre>{pretty(doc?.input_schema)}</pre>
                      <h4>输出／裁决契约</h4>
                      <pre>
                        {pretty(doc?.output_schema || doc?.verdict_schema)}
                      </pre>
                      <details open>
                        <summary>完整定义（含内部兼容字段）</summary>
                        <pre>{pretty(doc)}</pre>
                      </details>
                    </>
                  )}
                  <p className="muted">
                    字段契约、变量绑定、处理器和安全门禁由服务端维护。
                  </p>
                </section>
              </div>
              <section id="changes">
                <h2>变更对照</h2>
                {changed.length ? (
                  changed.map((name) => (
                    <details key={name}>
                      <summary>{name}</summary>
                      <div className="diff-grid">
                        <div>
                          <h4>配置基线</h4>
                          <pre>{pretty(original!.files[name])}</pre>
                        </div>
                        <div>
                          <h4>当前草稿</h4>
                          <pre>{pretty(draft.bundle.files[name])}</pre>
                        </div>
                      </div>
                    </details>
                  ))
                ) : (
                  <p className="muted">与配置基线一致。</p>
                )}
              </section>
            </>
          ))}
        {tab === 'runs' && (
          <>
            <section>
              <h2>调试记录</h2>
              <div className="table-scroll">
                <table className="inventory-table" aria-label="调试记录">
                  <thead>
                    <tr>
                      <th>调试对象</th>
                      <th>类型</th>
                      <th>配置来源</th>
                      <th>输入摘要</th>
                      <th>结果 / 时间</th>
                      <th className="right-cell">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state?.runs.map((item: Doc) => {
                      const target = runTarget(item, state.catalog);
                      return (
                        <tr key={item.id}>
                          <td>
                            <b>{target.name}</b>
                            <code>{target.id}</code>
                          </td>
                          <td>{target.type}</td>
                          <td>
                            {item.source_kind === 'draft'
                              ? `草稿修订 ${item.revision}`
                              : item.source_kind === 'release'
                                ? `发布 R${item.base_sequence}`
                                : item.base_sequence
                                  ? `基于 R${item.base_sequence}`
                                  : '基线未记录'}
                            <code>{item.digest.slice(0, 12)}</code>
                          </td>
                          <td>
                            {String(item.input.content || '').slice(0, 70)}
                          </td>
                          <td>
                            <span
                              className={
                                'badge ' +
                                (['failed', 'blocked'].includes(item.status)
                                  ? 'red'
                                  : '')
                              }
                            >
                              {labels[item.status]}
                            </span>
                            <small className="table-link">
                              {time(item.started_at)}
                            </small>
                          </td>
                          <td className="right-cell">
                            <button
                              className="secondary"
                              onClick={() =>
                                action(async () => {
                                  setRun({
                                    ...item,
                                    ...(await api('runs/' + item.id)),
                                  });
                                })
                              }
                            >
                              查看详情
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!state?.runs.length && <p className="empty">暂无调试记录。</p>}
            </section>
            {run && (
              <section aria-label="调试详情">
                <div className="section-head">
                  <div>
                    <h2>{runTarget(run, state?.catalog || null).name}</h2>
                    <code>
                      {runTarget(run, state?.catalog || null).id} ·{' '}
                      {runTarget(run, state?.catalog || null).type}
                    </code>
                  </div>
                  <div className="page-actions">
                    <button className="secondary" onClick={() => setRun(null)}>
                      收起详情
                    </button>
                  </div>
                </div>
                <p>
                  {run.source_kind === 'draft'
                    ? `已保存草稿 · 修订 ${run.revision}`
                    : run.source_kind === 'release'
                      ? `已发布配置 R${run.base_sequence}`
                      : run.base_sequence
                        ? `基于发布 R${run.base_sequence}`
                        : '历史基线未记录'}{' '}
                  · 快照 {run.digest?.slice(0, 12)}
                </p>
                <details>
                  <summary>本次调试输入</summary>
                  <pre>{pretty(run.input)}</pre>
                </details>
                {run.bundle && (
                  <details>
                    <summary>本次完整配置快照</summary>
                    <pre>{pretty(run.bundle)}</pre>
                  </details>
                )}
                {run.error ? (
                  <div className="notice error">{run.error}</div>
                ) : run.result ? (
                  <RunView result={run.result} />
                ) : (
                  <p>调试仍在进行中。</p>
                )}
              </section>
            )}
          </>
        )}
        {tab === 'releases' && state && (
          <>
            <section>
              <div className="section-head">
                <div>
                  <h2>
                    当前发布 {release ? `R${release.sequence}` : '尚未发布'}
                  </h2>
                  <code>{release?.digest.slice(0, 12)}</code>
                </div>
                <div className="page-actions">
                  {release && (
                    <button
                      className="secondary"
                      onClick={() => navigate('/releases/' + release.id)}
                    >
                      查看当前版本
                    </button>
                  )}
                </div>
              </div>
              <LoadStatus state={state} />
            </section>
            <section aria-label="当前待发布配置">
              <div className="section-head">
                <div>
                  <h2>待发布修改</h2>
                  {pending && (
                    <small>
                      {pending.changed_ids.length} 个组件变更 · 更新于{' '}
                      {time(pending.updated_at)}
                    </small>
                  )}
                </div>
                <div className="page-actions">
                  {!canEdit && pending && (
                    <button
                      className="secondary"
                      onClick={() => navigate(`/drafts/${pending.id}#changes`)}
                    >
                      查看变更与调试
                    </button>
                  )}
                  {canEdit && (
                    <>
                      {pending ? (
                        <>
                          <button
                            className="secondary"
                            disabled={busy}
                            onClick={() =>
                              action(async () => {
                                if (
                                  !window.confirm(
                                    '放弃当前全部待发布修改？历史发布和调试记录会保留。',
                                  )
                                )
                                  return;
                                await api(
                                  'drafts/' + pending.id + '/discard',
                                  'POST',
                                  { revision: pending.revision },
                                );
                                await refresh();
                                setMessage('待发布修改已放弃。');
                              })
                            }
                          >
                            放弃修改
                          </button>
                          <button
                            className="secondary"
                            onClick={() =>
                              navigate(`/drafts/${pending.id}#changes`)
                            }
                          >
                            查看变更
                          </button>
                          <button
                            className="secondary"
                            onClick={() => openDraft(pending.id)}
                          >
                            继续编辑
                          </button>
                          <button
                            className="secondary"
                            disabled={busy}
                            onClick={() =>
                              action(async () => {
                                await api(
                                  'drafts/' + pending.id + '/validate',
                                  'POST',
                                  { revision: pending.revision },
                                );
                                await refresh();
                                setMessage('配置校验通过');
                              })
                            }
                          >
                            校验配置
                          </button>
                          <button
                            disabled={
                              busy ||
                              !pending.validation ||
                              (!pending.changed_ids.length &&
                                state.environment.release_id !== null) ||
                              missing.length > 0 ||
                              pending.base_release_id !==
                                state.environment.release_id
                            }
                            onClick={() => action(publish)}
                          >
                            发布到
                            {state?.environment.name === 'prod'
                              ? '正式'
                              : '测试'}
                            环境
                          </button>
                        </>
                      ) : (
                        <button
                          className="secondary"
                          onClick={() => navigate('/agents')}
                        >
                          管理 Agent
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
              {pending ? (
                <>
                  {pending.base_release_id !== state.environment.release_id && (
                    <p className="notice">
                      当前发布已变化。请先核对并放弃旧修改，再从当前版本重新编辑。
                    </p>
                  )}
                  <div className="change-tags">
                    {pending.changed_ids.map((id: string) => (
                      <span key={id} className="badge">
                        {state.catalog?.components.find(
                          (item: Doc) => item.id === id,
                        )?.name || id}
                      </span>
                    ))}
                  </div>
                  <p>
                    {pending.validation ? '配置校验通过' : '尚未完成校验'} ·{' '}
                    {pending.required_components.length
                      ? successful.length
                        ? '已有本次修改的成功调试'
                        : '尚未完成本次修改的真实调试'
                      : '仅展示信息变更，无需调用模型'}
                    {missing.length > 0 && ` · 待验证：${missing.join('、')}`}
                  </p>
                </>
              ) : (
                <p>
                  暂无待发布修改。在 Agent
                  详情编辑配置后，将汇总到这里统一发布。
                </p>
              )}
            </section>
            <section>
              <h2>发布版本</h2>
              <div className="table-scroll">
                <table className="inventory-table" aria-label="发布版本">
                  <thead>
                    <tr>
                      <th>版本</th>
                      <th>发布时间</th>
                      <th>状态</th>
                      <th>摘要</th>
                      <th className="right-cell">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.releases.map((item: Doc) => (
                      <tr key={item.id}>
                        <td>
                          <a
                            href={'/releases/' + item.id}
                            onClick={(event) => {
                              event.preventDefault();
                              navigate('/releases/' + item.id);
                            }}
                          >
                            R{item.sequence}
                          </a>
                        </td>
                        <td>{time(item.created_at)}</td>
                        <td>
                          <span className="badge">
                            {item.id === release?.id
                              ? '当前发布'
                              : item.compatibility ===
                                  state.catalog?.bundle.compatibility
                                ? '可回滚'
                                : '旧协议 / 不兼容'}
                          </span>
                        </td>
                        <td>
                          <code>{item.digest.slice(0, 12)}</code>
                        </td>
                        <td>
                          <div className="page-actions">
                            <button
                              className="secondary"
                              onClick={() => navigate('/releases/' + item.id)}
                            >
                              查看版本
                            </button>
                            {canEdit && (
                              <button
                                className="secondary"
                                disabled={
                                  busy ||
                                  item.id === release?.id ||
                                  item.compatibility !==
                                    state.catalog?.bundle.compatibility
                                }
                                onClick={() =>
                                  action(() => rollback(item.id, item.sequence))
                                }
                              >
                                回滚到此版本
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
        {tab === 'release-detail' && specificVersion && (
          <VersionDetail
            key={specificVersion.id}
            version={specificVersion}
            canEdit={canEdit}
            currentId={state!.environment.release_id}
            compatible={
              specificVersion.bundle.compatibility ===
              state?.catalog?.bundle.compatibility
            }
            busy={busy}
            navigate={navigate}
            rollback={() =>
              action(() =>
                rollback(specificVersion.id, specificVersion.sequence),
              )
            }
          />
        )}
        {tab === 'agents' && state?.catalog && (
          <AgentInventory
            catalog={state.catalog}
            navigate={navigate}
            changedIds={pending?.changed_ids || []}
          />
        )}
        {tab === 'flows' && state?.catalog && (
          <WorkflowInventory catalog={state.catalog} navigate={navigate} />
        )}
        {tab === 'flow-detail' && state?.catalog?.workflows[entityId!] && (
          <>
            <div className="page-actions">
              {!draftId && state.environment.release_id && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={openPublishedDebug}
                >
                  调试已发布配置
                </button>
              )}
              {!draftId && pending && (
                <button
                  className="secondary"
                  onClick={() =>
                    navigate(`/workflows/${entityId}?draft=${pending.id}#debug`)
                  }
                >
                  调试已保存草稿
                </button>
              )}
              {draftId && draft && (
                <button
                  className="secondary"
                  onClick={() => setDebugOpen(true)}
                >
                  调试已保存草稿
                </button>
              )}
              {draftId && (
                <button
                  className="secondary"
                  onClick={() => navigate(`/workflows/${entityId}`)}
                >
                  返回已发布配置
                </button>
              )}
            </div>
            <WorkflowExplorer
              key={`${entityId}-${draftId || 'release'}`}
              catalog={
                graphSnapshot
                  ? {
                      ...state.catalog,
                      workflows: Object.fromEntries(
                        Object.values(graphSnapshot.bundle.files)
                          .filter((item: any) => item.kind === 'workflow')
                          .map((item: any) => [item.id, item]),
                      ),
                      definitions: Object.fromEntries(
                        Object.values(graphSnapshot.bundle.files)
                          .filter((item: any) =>
                            ['agent', 'gate', 'tool'].includes(item.kind),
                          )
                          .map((item: any) => [item.id, item]),
                      ),
                    }
                  : state.catalog
              }
              initialWorkflow={entityId!}
              navigate={navigate}
              execution={workflowRun?.events || []}
            />
          </>
        )}
        {(tab === 'missing' ||
          (tab === 'agent-detail' && state?.catalog && !agent) ||
          (tab === 'flow-detail' &&
            state?.catalog &&
            !state.catalog.workflows[entityId!])) && (
          <section>
            <h2>未找到此配置</h2>
            <p>请从 Agent 或 Workflow 列表选择已登记的配置。</p>
          </section>
        )}
        <DebugDrawer
          open={debugOpen}
          onClose={() => setDebugOpen(false)}
          loading={!graphSnapshot && !message}
          error={!graphSnapshot ? message : undefined}
        >
          {graphSnapshot && (tab !== 'agent-detail' || agent) && (
            <>
              {tab === 'config' && (
                <section>
                  <label>
                    调试对象
                    <select
                      aria-label="调试对象"
                      value={`${packageTarget.kind}:${packageTarget.id}`}
                      onChange={(e) => {
                        const [kind, id] = e.target.value.split(':');
                        setPackageTarget({
                          kind: kind as 'agent' | 'workflow',
                          id,
                        });
                      }}
                    >
                      {Object.values(graphSnapshot.bundle.files)
                        .filter(
                          (item: any) =>
                            item.kind === 'workflow' ||
                            ['agent', 'gate', 'tool'].includes(item.kind),
                        )
                        .map((item: any) => (
                          <option
                            key={item.id}
                            value={`${item.kind === 'workflow' ? 'workflow' : 'agent'}:${item.id}`}
                          >
                            {item.kind === 'workflow' ? 'Workflow' : '组件'} ·{' '}
                            {item.display_name || item.id}
                          </option>
                        ))}
                    </select>
                  </label>
                </section>
              )}
              <DebugPanel
                key={`${tab}-${entityId || packageTarget.id}-${graphSnapshot.id}-${graphSnapshot.revision}-${tab === 'config' ? packageTarget.id : ''}`}
                snapshot={graphSnapshot}
                source={draftId ? 'draft' : 'release'}
                target={
                  tab === 'agent-detail'
                    ? { kind: 'agent', id: agent.id }
                    : tab === 'flow-detail'
                      ? { kind: 'workflow', id: entityId! }
                      : packageTarget
                }
                capabilities={state?.catalog?.debug_capabilities || {}}
                dirty={!!draftId && dirty}
                onComplete={refresh}
                onResult={tab === 'flow-detail' ? setWorkflowRun : undefined}
                onInspect={tab === 'flow-detail' ? inspectWorkflow : undefined}
                navigate={(url) => {
                  setDebugOpen(false);
                  navigate(url);
                }}
              />
            </>
          )}
        </DebugDrawer>
        <footer>
          AGENT STUDIO ·{' '}
          {state?.environment.name === 'prod' ? '正式环境' : '测试环境'} ·
          配置与执行分离
        </footer>
      </main>
    </div>
  );
}
function DraftList({
  state,
  open,
}: {
  state: Doc | null;
  open: (id: string) => void;
}) {
  return (
    <section>
      <h2>待发布修改</h2>
      {!state?.drafts.length ? (
        <p className="empty">暂无待发布修改，请从Agent详情编辑配置。</p>
      ) : (
        state.drafts.map((d: Doc) => (
          <button
            key={d.id}
            className="list-row clickable"
            onClick={() => open(d.id)}
          >
            <span>
              <b>{d.title}</b>
              <small>更新于 {time(d.updated_at)}</small>
            </span>
            <span className="badge">{d.validation ? '已校验' : '待校验'}</span>
            <span>打开 →</span>
          </button>
        ))
      )}
    </section>
  );
}
