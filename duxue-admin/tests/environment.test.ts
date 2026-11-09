import test from 'node:test';
import assert from 'node:assert/strict';
import { environmentSettings } from '../src/lib/environment';
test('test/prod databases stay separate and prod requires a bare HTTPS origin', () => {
  const testSettings = environmentSettings(
    'test',
    'postgresql://user:password@localhost:5432/duxue-prod?sslmode=require',
  );
  assert.equal(new URL(testSettings.databaseUrl).pathname, '/duxue-admin-test');
  const prod = environmentSettings(
    'prod',
    testSettings.databaseUrl,
    'https://admin.duxuelai.xyz',
  );
  assert.equal(new URL(prod.databaseUrl).pathname, '/duxue-admin-prod');
  assert.equal(new URL(prod.databaseUrl).search, '?sslmode=require');
  assert.equal(prod.environment, 'prod');
  for (const origin of [
    undefined,
    'http://admin.duxuelai.xyz',
    'https://admin.duxuelai.xyz/',
    'https://admin.duxuelai.xyz/path',
  ])
    assert.throws(() =>
      environmentSettings('prod', testSettings.databaseUrl, origin),
    );
  assert.throws(() =>
    environmentSettings('production', testSettings.databaseUrl),
  );
  assert.throws(() => environmentSettings('test', 'sqlite:///tmp/test.db'));
});
