import assert from 'node:assert/strict';
import test from 'node:test';
import { studioRoute } from '../src/lib/studio-route';

test('list and detail URLs stay distinct and support deep links', () => {
  assert.equal(studioRoute('/').tab, 'flows');
  assert.equal(studioRoute('/audit').tab, 'missing');
  assert.deepEqual(studioRoute('/releases/version-id'), {
    tab: 'release-detail',
    id: 'version-id',
  });
  assert.deepEqual(studioRoute('/workflows'), { tab: 'flows', id: undefined });
  assert.deepEqual(studioRoute('/workflows/tutoring-vet'), {
    tab: 'flow-detail',
    id: 'tutoring-vet',
  });
  assert.deepEqual(studioRoute('/agents'), { tab: 'agents', id: undefined });
  assert.deepEqual(studioRoute('/agents/tutoring.turn'), {
    tab: 'agent-detail',
    id: 'tutoring.turn',
  });
  assert.deepEqual(studioRoute('/drafts/draft-id'), {
    tab: 'config',
    id: 'draft-id',
  });
  assert.equal(studioRoute('/agents/id/unexpected').tab, 'missing');
  assert.equal(studioRoute('/unknown').tab, 'missing');
});
