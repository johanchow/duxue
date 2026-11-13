/** Keep the displayed inventory tied to one explicit release or draft snapshot. */
export async function resolveCatalogSource(
  active: any,
  pending: any,
  load: (bundle: any) => Promise<any>,
) {
  const addedUnits =
    pending &&
    Object.keys(pending.bundle.files).some(
      (name) => !active?.bundle?.files?.[name],
    );
  let draftCatalog = !!addedUnits || !active;
  let sourceBundle = draftCatalog ? pending?.bundle : active.bundle;
  if (!sourceBundle) throw new Error('管理库尚无配置，请先导入完整配置快照');
  let catalog;
  try {
    catalog = await load(sourceBundle);
  } catch (error) {
    if (!pending || draftCatalog) throw error;
    sourceBundle = pending.bundle;
    catalog = await load(sourceBundle);
    draftCatalog = true;
  }
  return { catalog, draftCatalog };
}
