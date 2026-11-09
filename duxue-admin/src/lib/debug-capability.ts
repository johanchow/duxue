type Doc = Record<string, any>;
export type DebugTarget = { kind: 'agent' | 'workflow'; id: string };
export function debugCapability(
  target: DebugTarget,
  bundle: Doc,
  capabilities: Doc,
) {
  const definitions = Object.values(bundle.files) as Doc[];
  const definition = definitions.find((item) => item.id === target.id);
  const supported =
    target.kind === 'workflow'
      ? !!capabilities.workflows?.includes(target.id)
      : !!definition?.models?.length || !!capabilities.code_agents?.[target.id];
  if (supported)
    return {
      supported: true,
      reason: '',
      workflowId: undefined as string | undefined,
    };
  const consumers = new Set([
    target.id,
    ...definitions
      .filter((item) => item.tools?.includes(target.id))
      .map((item) => item.id),
  ]);
  const workflows = definitions.filter(
    (item) =>
      item.kind === 'workflow' &&
      item.nodes.some((node: Doc) => consumers.has(node.ref)),
  );
  const workflow =
    workflows.find((item) => capabilities.workflows?.includes(item.id)) ||
    workflows[0];
  const reason =
    capabilities.limitations?.[target.id] ||
    capabilities.limitations?.[definition?.handler_id] ||
    (definition?.kind === 'gate'
      ? '这是代码门禁，判断依赖流程中的候选结果、权限或执行状态，目前随所属 Workflow 一起调试。'
      : definition?.kind === 'tool' &&
          definition.handler_id === 'tool.static_result'
        ? '这是固定正文工具，目前尚未开放单独工具调试；可在完整配置中查看正文，并通过所属 Workflow 验证实际使用效果。'
        : definition?.kind === 'tool'
          ? '这个 Tool 需要调用方提供任务、题目或历史上下文，目前通过所属 Workflow 验证调用输入和结果。'
          : '这个代码组件依赖业务会话状态，目前尚未开放独立调试。');
  return {
    supported: false,
    reason,
    workflowId: workflow?.id as string | undefined,
  };
}
