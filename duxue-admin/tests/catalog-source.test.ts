import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveCatalogSource } from '../src/lib/catalog-source';

const active = {
  bundle: { files: { 'agents/old.json': { prompt: 'released' } } },
};
test('model-only pending edits do not masquerade as published configuration', async () => {
  const pending = {
    bundle: { files: { 'agents/old.json': { prompt: 'pending' } } },
  };
  const selected = await resolveCatalogSource(
    active,
    pending,
    async (bundle) => ({ bundle }),
  );
  assert.equal(selected.draftCatalog, false);
  assert.equal(selected.catalog.bundle, active.bundle);
});
test('new workflow inventory is explicitly shown as a draft', async () => {
  const pending = {
    bundle: {
      files: { ...active.bundle.files, 'workflows/observation.json': {} },
    },
  };
  const selected = await resolveCatalogSource(
    active,
    pending,
    async (bundle) => ({ bundle }),
  );
  assert.equal(selected.draftCatalog, true);
  assert.equal(selected.catalog.bundle, pending.bundle);
});
test('incompatible old release can be inspected through a valid upgrade draft', async () => {
  const pending = structuredClone(active);
  const selected = await resolveCatalogSource(
    active,
    pending,
    async (bundle) => {
      if (bundle === active.bundle) throw Error('obsolete contract');
      return { bundle };
    },
  );
  assert.equal(selected.draftCatalog, true);
  await assert.rejects(
    resolveCatalogSource(active, undefined, async () => {
      throw Error('invalid');
    }),
  );
});
