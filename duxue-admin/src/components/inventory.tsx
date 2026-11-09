'use client';
import { useMemo, useState } from 'react';
import {
  Background,
  BaseEdge,
  Controls,
  Panel,
  useReactFlow,
  ReactFlow,
  type EdgeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { workflowGraph, type Json } from '../lib/workflow-graph';
import { componentTypes } from '../lib/component-types';
import { nodeExecutions, edgeExecutions } from '../lib/execution-inspector';

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
      labelBgStyle={{ fill: '#f8faf8' }}
      labelBgPadding={[6, 4]}
    />
  );
}
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
  const components = catalog.components || catalog.agents || [];
  const agents = components.filter(
    (agent: Json) =>
      (type === 'all' || agent.type === type) &&
      `${agent.id} ${agent.name} ${agent.description}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
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
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="名称、ID 或作用"
          />
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
      </div>
      <div className="table-scroll">
        <table className="inventory-table" aria-label="Agent 列表">
          <thead>
            <tr>
              <th>Agent / ID</th>
              <th>作用简介</th>
              <th>类型</th>
              <th>修改状态</th>
              <th>所属 Workflow</th>
              <th>配置</th>
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
                    <span className="badge">有待发布修改</span>
                  ) : (
                    <span className="muted">—</span>
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
                <td>
                  {agent.editable ? '可编辑' : '只读'}
                  <a
                    className="table-link"
                    href={`/agents/${encodeURIComponent(agent.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    查看详情 →
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
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Workflow ID 或简介"
        />
      </label>
      <div className="table-scroll">
        <table className="inventory-table" aria-label="Workflow 列表">
          <thead>
            <tr>
              <th>Workflow</th>
              <th>简介</th>
              <th>配置</th>
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
                <td>
                  <a
                    href={`/workflows/${encodeURIComponent(flow.id)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(event.currentTarget.getAttribute('href')!);
                    }}
                  >
                    流程与配置 →
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
  return (
    <>
      <section aria-label="Agent 详情">
        <h2>
          配置信息{' '}
          <span className="badge">
            {componentTypes[agent.type] || agent.implementation}
          </span>
        </h2>
        <code>{agent.id}</code>
        {hasChanges && <span className="badge">有待发布修改</span>}
        <p>{agent.description}</p>
        <div className="agent-actions">
          {agent.workflows.map((id: string) => (
            <button
              className="secondary"
              key={id}
              onClick={() => navigate(`/workflows/${encodeURIComponent(id)}`)}
            >
              所属 Workflow：{id}
            </button>
          ))}
        </div>
        {editing && <p>当前环境唯一的待发布配置。</p>}
      </section>
      {!editing && (
        <section aria-label="Agent 完整配置">
          <h2>当前配置</h2>
          {catalog.source !== 'admin-release' && (
            <p className="notice">尚无已发布配置，当前展示已导入的草稿快照。</p>
          )}
          {definition.models && (
            <>
              <h3>模型</h3>
              <pre>
                {pretty(
                  definition.models.map(({ version, ...model }: Json) => model),
                )}
              </pre>
              <h3>主 Prompt</h3>
              <pre>{definition.prompt.template}</pre>
              <h3>Prompt 片段</h3>
              <pre>{pretty(definition.prompt.fragments || {})}</pre>
              <h3>工具</h3>
              <pre>{pretty(definition.tools)}</pre>
            </>
          )}
          <details>
            <summary>完整 JSON</summary>
            <pre>{pretty(definition)}</pre>
          </details>
        </section>
      )}
    </>
  );
}

export function WorkflowExplorer({
  catalog,
  initialWorkflow,
  navigate,
  execution = [],
}: {
  catalog: Json;
  initialWorkflow: string;
  execution?: Json[];
  navigate: (url: string) => void;
}) {
  const workflowId = initialWorkflow;
  const [selection, setSelection] = useState<{
    kind: string;
    config: Json;
    reference?: string;
  } | null>(null);
  const [showWhole, setShowWhole] = useState(false);
  const flow = catalog.workflows?.[workflowId];
  const graph = useMemo(
    () =>
      flow
        ? workflowGraph(flow, catalog.definitions)
        : { nodes: [], edges: [] },
    [flow, catalog.definitions],
  );
  if (!flow)
    return (
      <section>
        <p>未获取到流程配置，请检查服务端连接并刷新。</p>
      </section>
    );
  const nodes = graph.nodes.map((node) => {
    const config = flow.nodes.find((item: Json) => item.id === node.id);
    const events = config ? nodeExecutions(execution, workflowId, config) : [];
    return {
      ...node,
      className:
        node.className +
        (events.length
          ? events.some((event: Json) => event.status === 'failed')
            ? ' execution-failed'
            : ' execution-visited'
          : ''),
    };
  });
  const edges = graph.edges.map((edge) => {
    const events =
      edge.data?.configuration && !edge.data?.relationship
        ? edgeExecutions(execution, workflowId, edge.data.configuration as Json)
        : [];
    return events.some((event) => event.selected)
      ? { ...edge, style: { ...edge.style, stroke: '#1b8a62', strokeWidth: 4 } }
      : edge;
  });
  const selectionEvents = selection
    ? selection.kind === 'Node'
      ? nodeExecutions(execution, workflowId, selection.config)
      : selection.kind === 'Edge'
        ? edgeExecutions(execution, workflowId, selection.config)
        : []
    : [];
  const reference =
    selection?.reference && catalog.definitions?.[selection.reference];
  return (
    <>
      <section>
        <div className="section-head">
          <h2>
            Workflow 流程图 <span className="badge">只读</span>
          </h2>
          <div className="page-actions">
            <button
              className="secondary"
              onClick={() => navigate('/workflows')}
            >
              返回 Workflow 列表
            </button>
            <button
              className="secondary"
              onClick={() => setShowWhole(!showWhole)}
            >
              {showWhole ? '收起完整配置' : '查看完整 Workflow 配置'}
            </button>
          </div>
        </div>
        <h3>{workflowId}</h3>
        <p>
          {flow.id} · {flow.nodes.length} 个 Node · {flow.edges.length} 条 Edge
          · 入口 {flow.entry}
        </p>
        <p>
          点击节点或连线查看配置。实线表示控制流，虚线表示归属关系；重试回路按实际配置保留。
        </p>
        <div className="workflow-canvas" aria-label={`${workflowId} 流程图`}>
          <ReactFlow
            key={workflowId}
            nodes={nodes}
            edges={edges}
            edgeTypes={edgeTypes}
            fitView
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
              setSelection({
                kind: 'Node',
                config: config || { id: node.id, kind: 'boundary' },
                reference: config?.ref,
              });
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
        <div className="graph-inspector" aria-live="polite">
          {selection ? (
            <>
              <h3>{selection.kind} 配置</h3>
              <pre data-testid="selection-config">
                {pretty(selection.config)}
              </pre>
              {execution.length > 0 && (
                <div aria-label="选中对象执行数据">
                  <h3>本次执行数据</h3>
                  {selectionEvents.length ? (
                    selectionEvents.map((event) => (
                      <details key={event.id} open>
                        <summary>
                          执行 #{event.id} · {event.status}
                        </summary>
                        <pre>{pretty(event)}</pre>
                      </details>
                    ))
                  ) : (
                    <p>
                      本次没有该对象的执行记录。未经过的分支不会生成输入输出。
                    </p>
                  )}
                </div>
              )}
              {reference && (
                <>
                  <h3>引用组件完整配置 · {selection.reference}</h3>
                  {['agent', 'gate', 'tool'].includes(reference.kind) && (
                    <div className="page-actions">
                      <button
                        className="secondary"
                        onClick={() =>
                          navigate(
                            `/agents/${encodeURIComponent(reference.id)}`,
                          )
                        }
                      >
                        打开组件详情
                      </button>
                    </div>
                  )}
                  <pre>{pretty(reference)}</pre>
                </>
              )}
            </>
          ) : (
            <p>选择图中的 Node 或 Edge，查看原始配置与节点引用的组件定义。</p>
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
                onClick={() =>
                  setSelection({
                    kind: 'Node',
                    config: node,
                    reference: node.ref,
                  })
                }
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
