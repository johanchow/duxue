import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assertUpgradeSource } from '../src/lib/config-upgrade';

test('offline upgrade refuses concurrent edits, changed release and unrelated draft', () => {
  const source = { kind: 'release' as const, id: 'r1', digest: 'digest1' };
  assert.doesNotThrow(() => assertUpgradeSource(source, undefined, source));
  assert.throws(
    () => assertUpgradeSource(source, { id: 'd1', revision: 2 }, source),
    /工作草稿/,
  );
  assert.throws(
    () =>
      assertUpgradeSource(source, undefined, { id: 'r2', digest: 'digest2' }),
    /基线/,
  );
  const draft = {
    kind: 'draft' as const,
    id: 'd1',
    digest: 'digest',
    revision: 3,
  };
  assert.doesNotThrow(() =>
    assertUpgradeSource(draft, { id: 'd1', revision: 3 }, source),
  );
  assert.throws(
    () => assertUpgradeSource(draft, { id: 'd1', revision: 4 }, source),
    /草稿已变化/,
  );
  assert.throws(
    () => assertUpgradeSource(draft, { id: 'd2', revision: 3 }, source),
    /草稿已变化/,
  );
  assert.throws(
    () => assertUpgradeSource(draft, undefined, source),
    /草稿已变化/,
  );
});
