type Bundle = { files: Record<string, any> };
const selected = (value: any, fields: string[]) =>
  JSON.stringify(fields.map((field) => value?.[field] ?? null));
/** Require actual model component calls, not just another model in the same Agent. */
export function requiredDebugComponents(
  bundle: Bundle,
  baseline: Bundle,
): string[] {
  const required = new Set<string>();
  for (const [file, definition] of Object.entries(bundle.files)) {
    const before = baseline.files[file];
    if (definition.models) {
      const sharedChanged =
        selected(definition, ['prompt', 'tools']) !==
        selected(before, ['prompt', 'tools']);
      for (const model of definition.models) {
        const previous = before?.models?.find(
          (item: any) => item.component_id === model.component_id,
        );
        if (sharedChanged || JSON.stringify(model) !== JSON.stringify(previous))
          required.add(model.component_id);
      }
    }
    if (
      definition.kind === 'tool' &&
      selected(definition, ['static_result']) !==
        selected(before, ['static_result'])
    ) {
      for (const unit of Object.values(bundle.files)) {
        if (unit.models && unit.tools?.includes(definition.id))
          unit.models.forEach((model: any) => required.add(model.component_id));
      }
    }
  }
  return [...required].sort();
}
