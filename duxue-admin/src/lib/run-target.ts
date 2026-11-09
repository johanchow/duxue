type Doc = Record<string, any>;
export function runTarget(run: Doc, catalog: Doc | null) {
  const kind = run.target_kind || run.input?.target_kind;
  const targetId = run.target_id || run.input?.target_id;
  if (kind && targetId) {
    const component = catalog?.components?.find(
      (item: Doc) => item.id === targetId,
    );
    return {
      id: targetId,
      name: component?.name || targetId,
      type: kind === 'workflow' ? '流程调试' : '组件调试',
    };
  }
  const id = run.input?.component_id || 'tutoring-pipeline';
  if (id === 'tutoring-pipeline')
    return { id, name: 'Tutoring 答疑流程', type: '流程调试' };
  const definition = Object.values(catalog?.definitions || {}).find(
    (item: any) => item.models?.some((model: any) => model.component_id === id),
  ) as Doc | undefined;
  const component = catalog?.components?.find(
    (item: Doc) => item.id === definition?.id,
  );
  return {
    id,
    name: component?.name || definition?.display_name || id,
    type: '组件调试',
  };
}
