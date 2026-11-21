'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  BaseEdge,
  Controls,
  Handle,
  Panel,
  useReactFlow,
  ReactFlow,
  type EdgeProps,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  workflowDetailHref,
  workflowGraph,
  workflowNodeTitle,
  type Json,
} from '../lib/workflow-graph';
import {
  tutoringHierarchy,
  isTutoringAttempt,
} from '../lib/tutoring-hierarchy';
import { actionLogic, gateLogic } from '../lib/workflow-code';
import { componentTypes } from '../lib/component-types';
import { filterAgents } from '../lib/agent-filter';
import {
  nodeExecutions,
  edgeExecutions,
  executionChildren,
  executionForCall,
  nodeVisits,
  type ExecutionCall,
} from '../lib/execution-inspector';
import { IconArrowRight, IconCode, IconSearch, IconWorkflow } from './icons';

function CatalogEdge({ id, data, label, markerEnd, style }: EdgeProps) {
  const points = data?.route as { x: number; y: number }[];
  const path = points
    .map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`)
    .join(' ');
  return (
    <BaseEdge
      id={id}
      path={path}
      label={label}
      labelX={data?.labelX as number}
      labelY={data?.labelY as number}
      markerEnd={markerEnd}
      style={style}
      interactionWidth={24}
      labelStyle={{ fontSize: 11 }}
      labelBgStyle={{ fill: '#ffffff', stroke: '#d9e3dd', strokeWidth: 1 }}
      labelBgBorderRadius={5}
      labelBgPadding={[6, 4]}
    />
  );
}
function WorkflowCard({ data, sourcePosition, targetPosition }: NodeProps) {
  const title = String(data.title);
  const typeLabel = data.typeLabel as string | undefined;
  const reference = data.reference as string | undefined;
  const href = data.href as string | undefined;
  const content = (
    <>
      <strong className="workflow-card-title" title={title}>
        {title}
      </strong>
      {typeLabel && (
        <span className="workflow-card-meta">
          {typeLabel}
          {data.required ? ' · 必经' : ''}
        </span>
      )}
      {reference && (
        <code className="workflow-card-ref" title={reference}>
          {reference}
        </code>
      )}
      {href && (
        <span className="workflow-card-arrow">
          <IconArrowRight size={17} />
        </span>
      )}
    </>
  );
  return (
    <>
      <Handle id="in" type="target" position={targetPosition!} />
      {href ? (
        <a
          className="workflow-card nodrag nopan"
          href={href}
          onClick={(event) => {
            event.stopPropagation();
            if (
              event.metaKey ||
              event.ctrlKey ||
              event.shiftKey ||
              event.altKey
            )
              return;
            event.preventDefault();
            (data.navigate as (url: string) => void)(href);
          }}
        >
          {content}
        </a>
      ) : (
        <div className="workflow-card">{content}</div>
      )}
      <Handle id="out" type="source" position={sourcePosition!} />
    </>
  );
}
const nodeTypes = { workflowCard: WorkflowCard };

const edgeTypes = { catalog: CatalogEdge };
function ReadableView() {
  const { zoomTo, fitView } = useReactFlow();
  return (
    <Panel position="top-right">
      <div className="graph-view-actions">
        <button className="secondary" onClick={() => zoomTo(1)}>
          100% 查看
        </button>
        <button className="secondary" onClick={() => fitView({ padding: 0.1 })}>
          适应全图
        </button>
      </div>
    </Panel>
  );
}

const pretty = (value: unknown) => JSON.stringify(value, null, 2);
export function AgentInventory({
  catalog,
  navigate,
  changedIds = [],
}: {
  catalog: Json;
  navigate: (url: string) => void;
  changedIds?: string[];
}) {
  const [query, setQuery] = useState('');
  const [type, setType] = useState('all');
  const [workflow, setWorkflow] = useState('all');
  const components: Json[] = catalog.components || catalog.agents || [];
  const workflows = Object.keys(catalog.workflows || {}).sort();
  const agents = filterAgents(components as (Json & { id: string })[], {
    query,
    type,
    workflow,
  });
  return (
    <section>
      <h2>
        Agent 列表{' '}
        <span className="badge">
          共 {catalog.counts.components ?? catalog.counts.agents} 项
        </span>
      </h2>
      <div className="agent-filters">
        <label>
          搜索 Agent
          <span className="search-field">
            <IconSearch />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="名称、ID 或作用"
            />
          </span>
        </label>
        <label>
          类型
          <select
            aria-label="类型"
            value={type}
            onChange={(event) => setType(event.target.value)}
          >
            <option value="all">全部类型（{components.length}）</option>
            {Object.entries(componentTypes).map(([value, label]) => (
              <option key={value} value={value}>
                {label}（
                {components.filter((item: Json) => item.type === value).length}
                ）
              </option>
            ))}
          </select>
        </label>
        <label>
          所属 Workflow
          <select
            aria-label="所属 Workflow"
            value={workflow}
            onChange={(event) => setWorkflow(event.target.value)}
          >
            <option value="all">全部 Workflow</option>
            {workflows.map((id) => (
              <option key={id} value={id}>
                {id}（
                {
                  components.filter((agent) => agent.workflows?.includes(id))
                    .length
                }
                ）
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted" role="status">
        当前匹配 {agents.length} 项
      </p>
      <div className="table-scroll">
        <table className="inventory-table" aria-label="Agent 列表">
          <thead>
            <tr>
              <th>Agent / ID</th>
              <th>作用简介</th>
              <th>类型</th>
              <th>状态</th>
              <th>所属 Workflow</th>
              <th className="right-cell">操作</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent: Json) => (
              <tr key={agent.id}>
                <td>
                  <a
                    href={`/agents/${encodeURIComponent(agent.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    {agent.name}
                  </a>
                  <code>{agent.id}</code>
                </td>
                <td>{agent.description}</td>
                <td>{componentTypes[agent.type] || agent.implementation}</td>
                <td>
                  {changedIds.includes(agent.id) ? (
                    <span
                      className="badge"
                      title="该 Agent 与草稿基线存在差异；草稿调试可使用修改，发布并加载后才会影响正常运行。"
                    >
                      有待发布修改
                    </span>
                  ) : (
                    <span className="muted-tag">已发布</span>
                  )}
                </td>
                <td>
                  {agent.workflows.map((id: string) => (
                    <a
                      className="table-link"
                      key={id}
                      href={`/workflows/${encodeURIComponent(id)}`}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate(event.currentTarget.getAttribute('href')!);
                      }}
                    >
                      {id}
                    </a>
                  ))}
                </td>
                <td className="right-cell">
                  <a
                    className="button-link secondary btn-sm"
                    href={`/agents/${encodeURIComponent(agent.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    查看详情
                    <IconArrowRight size={14} />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!agents.length && <p className="empty">没有匹配的 Agent</p>}
    </section>
  );
}

export function WorkflowInventory({
  catalog,
  navigate,
}: {
  catalog: Json;
  navigate: (url: string) => void;
}) {
  const [query, setQuery] = useState('');
  const flows = Object.values(catalog.workflows as Record<string, Json>).filter(
    (flow) =>
      `${flow.id} ${catalog.workflow_descriptions?.[flow.id] || ''}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <section>
      <h2>
        Workflow 列表{' '}
        <span className="badge">共 {catalog.counts.workflows} 个</span>
      </h2>
      <p>
        按当前代码登记的流程展示。Node包含模型/代码Agent、Gate以及固定代码Action；重试回路按原配置保留。
      </p>
      <label>
        搜索 Workflow
        <span className="search-field">
          <IconSearch />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Workflow ID 或简介"
          />
        </span>
      </label>
      <div className="table-scroll">
        <table className="inventory-table" aria-label="Workflow 列表">
          <thead>
            <tr>
              <th>Workflow</th>
              <th>简介</th>
              <th className="right-cell">操作</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((flow) => (
              <tr key={flow.id}>
                <td>
                  <a
                    href={`/workflows/${encodeURIComponent(flow.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    {flow.id}
                  </a>
                </td>
                <td>
                  {catalog.workflow_descriptions?.[flow.id] || '暂无简介'}
                </td>
                <td className="right-cell">
                  <a
                    className="button-link secondary btn-sm"
                    href={`/workflows/${encodeURIComponent(flow.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    流程与配置
                    <IconArrowRight size={14} />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!flows.length && <p className="empty">没有匹配的 Workflow</p>}
    </section>
  );
}

export function AgentDetail({
  catalog,
  agent,
  navigate,
  editing,
  hasChanges,
}: {
  hasChanges: boolean;
  catalog: Json;
  agent: Json;
  navigate: (url: string) => void;
  editing: boolean;
}) {
  const definition = catalog.definitions[agent.id];
  const fragments = Object.entries(definition?.prompt?.fragments || {}) as [
    string,
    Json,
  ][];
  return (
    <>
      <section aria-label="Agent 详情">
        <div className="section-head">
          <div>
            <h2>
              基本信息{' '}
              <span className="badge">
                {componentTypes[agent.type] || agent.implementation}
              </span>
              {hasChanges ? (
                <span
                  className="badge"
                  title="该 Agent 与草稿基线存在差异；草稿调试可使用修改，发布并加载后才会影响正常运行。"
                >
                  有待发布修改
                </span>
              ) : (
                <span className="badge badge-neutral">已发布</span>
              )}
            </h2>
            <code>{agent.id}</code>
          </div>
          {!!agent.workflows.length && (
            <div className="page-actions">
              {agent.workflows.map((id: string) => (
                <button
                  className="secondary btn-sm"
                  key={id}
                  onClick={() =>
                    navigate(`/workflows/${encodeURIComponent(id)}`)
                  }
                >
                  <IconWorkflow size={14} />
                  所属 Workflow：{id}
                </button>
              ))}
            </div>
          )}
        </div>
        <p>{agent.description}</p>
        {editing && <p className="muted">当前环境唯一的待发布配置。</p>}
      </section>
      {agent.type === 'code-gate' && (
        <section aria-label="执行逻辑">
          <h2>执行逻辑</h2>
          <p>
            {gateLogic(definition) || agent.description || '暂无逻辑摘要。'}
          </p>
          <p className="compact-meta">
            代码处理器 <code>{definition.handler_id}</code>
          </p>
        </section>
      )}
      {!editing && (
        <>
          <section aria-label="当前配置">
            <div className="section-head">
              <h2>当前配置</h2>
              <span className="badge badge-neutral">
                {catalog.source !== 'admin-release'
                  ? '待发布草稿'
                  : '已发布配置'}
              </span>
            </div>
            {catalog.source !== 'admin-release' && (
              <p className="notice">当前展示待发布草稿，尚未应用到运行环境。</p>
            )}
            {definition.models ? (
              <>
                <h3>模型与预算</h3>
                <div className="model-summary-list">
                  {definition.models.map((model: Json, index: number) => (
                    <div
                      className="model-summary-card"
                      key={model.component_id || index}
                    >
                      <div className="model-summary-title">
                        <span className="badge badge-neutral">
                          {index ? '备用模型' : '主模型'}
                        </span>
                        <strong>{model.name}</strong>
                      </div>
                      <div className="model-summary-meta">
                        <span>温度 {model.temperature}</span>
                        <span>Token 上限 {model.max_output_tokens}</span>
                        <span>超时 {model.timeout_ms}ms</span>
                        {model.enable_thinking ? (
                          <span>
                            思考开启
                            {model.thinking_budget
                              ? ` (预算 ${model.thinking_budget})`
                              : ''}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
                <h3>主 Prompt</h3>
                <pre>{definition.prompt.template}</pre>
                <h3>
                  具名指令片段 <small>{fragments.length} 项</small>
                </h3>
                {fragments.length ? (
                  fragments.map(([name, value]) => (
                    <details key={name}>
                      <summary>
                        {name}
                        <small>{value.id}</small>
                      </summary>
                      <pre>{value.template}</pre>
                      <code>
                        变量：
                        {Object.keys(value.variables || {}).join('、') || '无'}
                      </code>
                    </details>
                  ))
                ) : (
                  <p className="muted">无具名指令片段。</p>
                )}
                <h3>已启用工具</h3>
                {definition.tools?.length ? (
                  <div className="change-tags">
                    {definition.tools.map((tool: string) => (
                      <span className="badge badge-neutral" key={tool}>
                        {tool}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">当前未启用工具。</p>
                )}
              </>
            ) : definition.static_result ? (
              <>
                <h3>工具静态正文</h3>
                <pre>{definition.static_result.guidelines}</pre>
              </>
            ) : (
              <p className="muted">
                核心实现由服务端代码维护，仅显示名称与简介可在草稿中调整。
              </p>
            )}
          </section>
          <section aria-label="Agent 完整配置">
            <div className="section-head">
              <div>
                <h2>底层契约与完整定义</h2>
                <p className="compact-meta">
                  字段契约、变量绑定、处理器和安全门禁由服务端维护。
                </p>
              </div>
            </div>
            <details>
              <summary>查看完整 JSON</summary>
              <pre>{pretty(definition)}</pre>
            </details>
          </section>
        </>
      )}
    </>
  );
}

export function WorkflowActionDetail({
  flow,
  catalog,
  node,
  definitions,
  names,
}: {
  flow: Json;
  catalog: Json;
  node: Json;
  definitions: Record<string, Json>;
  names: Record<string, string>;
}) {
  const summary = actionLogic(flow.id, node);
  const hierarchy = tutoringHierarchy(catalog.workflows);
  const outgoing = flow.edges.filter((edge: Json) => edge.from === node.id);
  return (
    <>
      <section aria-label="执行逻辑">
        <h2>
          执行逻辑{' '}
          <span className="badge badge-neutral">Action · 固定代码</span>
        </h2>
        <p>{summary?.summary || '暂无逻辑摘要，可查看下方分支和节点配置。'}</p>
        <p className="compact-meta">
          代码处理器 <code>{node.handler_id}</code>
        </p>
        {hierarchy && isTutoringAttempt(flow, node, hierarchy) && (
          <>
            <h3>本次尝试</h3>
            <ol>
              <li>
                启发式答疑生成 · <code>{hierarchy.attempt.ref}</code>
              </li>
              <li>
                取得可审核的候选后进入出口审核 ·{' '}
                <a
                  href={workflowDetailHref(
                    'tutoring',
                    hierarchy.review,
                    undefined,
                    catalog.source_draft?.id,
                    catalog.source_release?.id,
                  )}
                >
                  查看审核流程
                </a>
              </li>
            </ol>
          </>
        )}
        {outgoing.length > 0 && (
          <>
            <h3>后续路径</h3>
            <ul>
              {outgoing.map((edge: Json, index: number) => {
                const target = flow.nodes.find(
                  (item: Json) => item.id === edge.to,
                );
                const title = target
                  ? workflowNodeTitle(
                      flow.id,
                      target,
                      definitions[target.ref],
                      names[target.ref],
                    )
                  : edge.to === 'END'
                    ? '结束'
                    : edge.to;
                return (
                  <li key={index}>
                    {title}
                    {edge.condition_id ? (
                      <>
                        {' '}
                        · <code>{edge.condition_id}</code>
                      </>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>
      <section>
        <details>
          <summary>节点配置</summary>
          <pre>{pretty(node)}</pre>
        </details>
      </section>
    </>
  );
}

function ReplayVisit({
  event,
  events,
  workflows,
  activeEvent,
  openCall,
  expanded,
}: {
  event: Json;
  events: Json[];
  workflows: Record<string, Json>;
  activeEvent: Json | null;
  openCall: (call: ExecutionCall) => void;
  expanded: boolean;
}) {
  const children = executionChildren(events, workflows, event);
  const { input, output, ...details } = event;
  return (
    <details open={expanded || activeEvent?.id === event.id}>
      <summary>
        #{event.id} ·{' '}
        {event.kind === 'model' ? '模型调用' : event.node_id || event.kind}
        {event.model ? ` · ${event.model}` : ''} · {event.status} ·{' '}
        {event.duration_ms == null ? '耗时未记录' : `${event.duration_ms} ms`}
      </summary>
      {children.map((child) =>
        child.type === 'workflow' ? (
          <button
            key={child.event.id}
            type="button"
            className="secondary btn-sm"
            onClick={() => openCall(child)}
          >
            查看子流程 {child.workflowId} · #{child.event.id}
          </button>
        ) : (
          <ReplayVisit
            key={child.event.id}
            event={child.event}
            events={events}
            workflows={workflows}
            activeEvent={activeEvent}
            openCall={openCall}
            expanded={
              child.event.kind === 'model' ||
              (!!event.node_id && child.event.node_id === event.node_id)
            }
          />
        ),
      )}
      {input !== undefined && (
        <>
          <h4>输入</h4>
          <pre>{typeof input === 'string' ? input : pretty(input)}</pre>
        </>
      )}
      {output !== undefined && (
        <>
          <h4>输出</h4>
          <pre>{typeof output === 'string' ? output : pretty(output)}</pre>
        </>
      )}
      <details>
        <summary>事件与状态</summary>
        <pre>{pretty(details)}</pre>
      </details>
    </details>
  );
}

export function WorkflowExplorer({
  catalog,
  initialWorkflow,
  navigate,
  execution: allEvents = [],
  activeEvent = null,
  draftId,
}: {
  catalog: Json;
  initialWorkflow: string;
  execution?: Json[];
  activeEvent?: Json | null;
  draftId?: string;
  navigate: (url: string) => void;
}) {
  const [calls, setCalls] = useState<ExecutionCall[]>([]);
  const inspector = useRef<HTMLDivElement>(null);
  const call = calls.at(-1);
  const workflowId = call?.workflowId || initialWorkflow;
  const replay =
    allEvents.length > 0 || catalog.source === 'execution-snapshot';
  const execution = call ? executionForCall(allEvents, call) : allEvents;
  function openCall(call: ExecutionCall) {
    setSelection(null);
    setCalls((previous) => [...previous, call]);
  }
  function inspectNode(node: Json) {
    setSelection({ kind: 'Node', config: node, reference: node.ref });
    if (replay)
      requestAnimationFrame(() =>
        inspector.current?.scrollIntoView({ block: 'start' }),
      );
  }
  const [selection, setSelection] = useState<{
    kind: string;
    config: Json;
    reference?: string;
  } | null>(null);
  const [direction, setDirection] = useState<'LR' | 'TB'>('LR');
  const [showWhole, setShowWhole] = useState(false);
  const flow = catalog.workflows?.[workflowId];
  const detailHref = (node?: Json) =>
    workflowDetailHref(
      workflowId,
      node,
      catalog.definitions?.[node?.ref],
      draftId || catalog.source_draft?.id,
      catalog.source_release?.id,
    );
  const graph = useMemo(
    () =>
      flow
        ? workflowGraph(
            flow,
            catalog.definitions,
            Object.fromEntries(
              (catalog.components || []).map((component: Json) => [
                component.id,
                component.name,
              ]),
            ),
            direction,
          )
        : { nodes: [], edges: [] },
    [flow, catalog.definitions, catalog.components, direction],
  );
  useEffect(() => {
    if (!activeEvent || !flow || activeEvent.workflow_id !== workflowId) return;
    if (activeEvent.kind === 'edge') {
      const edge = flow.edges?.find(
        (item: Json) =>
          edgeExecutions([activeEvent], workflowId, item).length > 0,
      );
      if (edge) setSelection({ kind: 'Edge', config: edge });
      return;
    }
    const node = flow.nodes?.find(
      (item: Json) =>
        nodeExecutions([activeEvent], workflowId, item).length > 0,
    );
    if (node) {
      setSelection({
        kind: 'Node',
        config: node,
        reference: node.ref,
      });
    }
  }, [activeEvent?.id, workflowId, flow]);
  if (!flow)
    return (
      <section>
        <p>未获取到流程配置，请检查服务端连接并刷新。</p>
      </section>
    );
  const nodes = graph.nodes.map((node) => {
    const config = flow.nodes.find((item: Json) => item.id === node.id);
    const events = config ? nodeExecutions(execution, workflowId, config) : [];
    const isCurrent =
      activeEvent &&
      config &&
      nodeExecutions([activeEvent], workflowId, config).length > 0;
    return {
      ...node,
      data: {
        ...node.data,
        href: replay ? undefined : detailHref(config),
        navigate,
      },
      className:
        node.className +
        (events.length
          ? events.some((event: Json) => event.status === 'failed')
            ? ' execution-failed'
            : ' execution-visited'
          : execution.length
            ? ' execution-unvisited'
            : '') +
        (isCurrent ? ' execution-current' : ''),
    };
  });
  const edges = graph.edges.map((edge) => {
    const events =
      edge.data?.configuration && !edge.data?.relationship
        ? edgeExecutions(execution, workflowId, edge.data.configuration as Json)
        : [];
    const isCurrent =
      activeEvent &&
      edge.data?.configuration &&
      !edge.data?.relationship &&
      edgeExecutions([activeEvent], workflowId, edge.data.configuration as Json)
        .length > 0;
    if (isCurrent) {
      return {
        ...edge,
        animated: true,
        style: { ...edge.style, stroke: '#d97706', strokeWidth: 4 },
      };
    }
    return events.some((event) => event.selected)
      ? { ...edge, style: { ...edge.style, stroke: '#1b8a62', strokeWidth: 4 } }
      : edge;
  });
  const selectionEvents = selection
    ? selection.kind === 'Node'
      ? nodeVisits(execution, workflowId, selection.config)
      : selection.kind === 'Edge'
        ? edgeExecutions(execution, workflowId, selection.config)
        : []
    : [];
  const reference =
    selection?.reference && catalog.definitions?.[selection.reference];
  return (
    <>
      <section>
        {call && (
          <button
            className="secondary"
            onClick={() => {
              setCalls(calls.slice(0, -1));
              setSelection(null);
            }}
          >
            返回父流程 · 调用 #{call.event.id}
          </button>
        )}
        <div className="section-head">
          <div>
            <h2>
              Workflow 流程图 <span className="badge">只读</span>
            </h2>
            <p className="compact-meta">
              {flow.id} · {flow.nodes.length} 个 Node · {flow.edges.length} 条
              Edge · 入口 {flow.entry}
            </p>
          </div>
          <div className="page-actions">
            <button
              className="secondary"
              onClick={() => setShowWhole(!showWhole)}
            >
              <IconCode />
              {showWhole ? '收起完整配置' : '查看完整 Workflow 配置'}
            </button>
          </div>
        </div>
        <p className="muted">
          {replay
            ? '点击节点查看输入、输出和本次调用的子流程。'
            : '点击带箭头的节点打开详情，点击连线查看分支配置。'}
        </p>
        <div className="workflow-toolbar">
          <div className="workflow-legend" aria-label="流程图图例">
            <span className="legend-agent">Agent</span>
            <span className="legend-gate">Gate</span>
            <span className="legend-action">Action</span>
            {flow.nodes.some((n: Json) => n.kind === 'workflow') && (
              <span className="legend-workflow">Workflow · 子流程</span>
            )}
            <span className="legend-parent">虚线 · 归属</span>
          </div>
          <div
            className="workflow-directions"
            role="group"
            aria-label="布局方向"
          >
            <button
              className="secondary"
              aria-pressed={direction === 'LR'}
              onClick={() => setDirection('LR')}
            >
              横向
            </button>
            <button
              className="secondary"
              aria-pressed={direction === 'TB'}
              onClick={() => setDirection('TB')}
            >
              纵向
            </button>
          </div>
        </div>
        <div className="workflow-canvas" aria-label={`${workflowId} 流程图`}>
          <ReactFlow
            key={`${workflowId}:${direction}`}
            nodes={nodes}
            edges={edges}
            edgeTypes={edgeTypes}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={
              execution.length
                ? {
                    nodes: nodes.filter(
                      (n) =>
                        n.className?.includes('execution-visited') ||
                        n.className?.includes('execution-failed'),
                    ),
                    padding: 0.15,
                    minZoom: 0.1,
                    maxZoom: 1,
                  }
                : { padding: 0.1, minZoom: 0.65, maxZoom: 1 }
            }
            minZoom={0.1}
            maxZoom={2}
            nodesDraggable={false}
            nodesConnectable={false}
            edgesReconnectable={false}
            deleteKeyCode={null}
            onNodeClick={(_, node) => {
              const config = flow.nodes.find(
                (item: Json) => item.id === node.id,
              );
              const href = detailHref(config);
              if (
                replay &&
                config?.kind === 'workflow' &&
                catalog.workflows[config.ref]
              ) {
                const events = nodeExecutions(execution, workflowId, config);
                const children =
                  events.length === 1
                    ? executionChildren(execution, catalog.workflows, events[0])
                    : [];
                const child = children.length === 1 ? children[0] : null;
                if (
                  child?.type === 'workflow' &&
                  child.workflowId === config.ref
                ) {
                  openCall(child);
                  return;
                }
              }
              if (!replay && href) {
                navigate(href);
                return;
              }
              inspectNode(config || { id: node.id, kind: 'boundary' });
            }}
            onEdgeClick={(_, edge) =>
              setSelection({
                kind: edge.data?.relationship ? 'Parent 关系' : 'Edge',
                config: edge.data?.configuration as Json,
              })
            }
          >
            <ReadableView />
            <Background gap={22} />
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        </div>
        <div className="graph-inspector" aria-live="polite" ref={inspector}>
          {selection ? (
            <>
              {replay && (
                <div aria-label="选中对象执行数据">
                  <h3>
                    本次执行数据 · {selection.config?.id || selection.kind}
                  </h3>
                  {selectionEvents.length ? (
                    selectionEvents.map((event) => (
                      <ReplayVisit
                        key={event.id}
                        event={event}
                        events={execution}
                        workflows={catalog.workflows}
                        activeEvent={activeEvent}
                        openCall={openCall}
                        expanded
                      />
                    ))
                  ) : (
                    <p>本次没有该对象的执行记录。</p>
                  )}
                </div>
              )}
              {replay ? (
                <details>
                  <summary>{selection.kind} 配置</summary>
                  <pre data-testid="selection-config">
                    {pretty(selection.config)}
                  </pre>
                </details>
              ) : (
                <>
                  <h3>{selection.kind} 配置</h3>
                  <pre data-testid="selection-config">
                    {pretty(selection.config)}
                  </pre>
                </>
              )}
              {selection.kind === 'Node' &&
                selection.config.kind === 'action' && (
                  <div className="page-actions">
                    <button
                      className="secondary btn-sm"
                      onClick={() => navigate(detailHref(selection.config)!)}
                    >
                      {catalog.source === 'execution-snapshot'
                        ? '打开当前步骤详情'
                        : '打开步骤详情'}
                      <IconArrowRight size={14} />
                    </button>
                  </div>
                )}
              {reference && (
                <>
                  <div className="section-head inspector-head">
                    <h3>
                      {catalog.source === 'execution-snapshot'
                        ? '执行时组件标识'
                        : '引用组件完整配置'}{' '}
                      · {selection.reference}
                    </h3>
                    {['agent', 'gate', 'tool'].includes(reference.kind) && (
                      <div className="page-actions">
                        <button
                          className="secondary btn-sm"
                          onClick={() =>
                            navigate(
                              detailHref(selection.config) ||
                                `/agents/${encodeURIComponent(reference.id)}`,
                            )
                          }
                        >
                          {catalog.source === 'execution-snapshot'
                            ? '打开当前组件配置'
                            : '打开组件详情'}
                          <IconArrowRight size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                  <pre>{pretty(reference)}</pre>
                </>
              )}
            </>
          ) : (
            <p>
              {replay
                ? '选择图中的节点或连线，查看本次回放数据。'
                : '选择图中的 Node 或 Edge，查看原始配置与节点引用的组件定义。'}
            </p>
          )}
        </div>
        <details>
          <summary>Node / Edge 配置索引</summary>
          <h3>Node</h3>
          <div className="config-index">
            {flow.nodes.map((node: Json) => (
              <button
                className="secondary"
                key={node.id}
                onClick={() => inspectNode(node)}
              >
                {node.id}
              </button>
            ))}
          </div>
          <h3>Edge</h3>
          <div className="config-index">
            {flow.edges.map((edge: Json, index: number) => (
              <button
                className="secondary"
                key={index}
                onClick={() => setSelection({ kind: 'Edge', config: edge })}
              >
                {edge.from} → {edge.to} · {edge.condition_id || '无条件'}
              </button>
            ))}
          </div>
        </details>
        {showWhole && (
          <div aria-label="Workflow 完整配置">
            <h3>完整 Workflow 配置（只读）</h3>
            <pre>{pretty(flow)}</pre>
          </div>
        )}
      </section>
    </>
  );
}
