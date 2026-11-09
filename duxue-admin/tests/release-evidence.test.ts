import test from 'node:test';
import assert from 'node:assert/strict';
import { requiredDebugComponents } from '../src/lib/release-evidence';
test('publishing a changed non-tutoring model needs its own exact-snapshot debug', () => {
  const base = {
    files: {
      'agents/companion.intent.json': {
        id: 'companion.intent',
        kind: 'agent',
        models: [{ component_id: 'companion.intent', name: 'one' }],
        prompt: { template: 'before' },
        tools: [],
      },
      'agents/planning.session-turn.json': {
        id: 'planning.session-turn',
        kind: 'agent',
      },
    },
  };
  const next = structuredClone(base);
  next.files['agents/companion.intent.json'].prompt.template = 'after';
  assert.deepEqual(requiredDebugComponents(next, base), ['companion.intent']);
  const metadata = structuredClone(base) as any;
  metadata.files['agents/planning.session-turn.json'].display_name = '新名称';
  assert.deepEqual(requiredDebugComponents(metadata, base), []);
});

test('a backup model edit requires that backup, and shared prompts require both', () => {
  const base = {
    files: {
      'agent.json': {
        id: 'tutoring.turn',
        models: [
          { component_id: 'primary', name: 'a' },
          { component_id: 'backup', name: 'b' },
        ],
        prompt: { template: 'before' },
        tools: [],
      },
    },
  };
  const next = structuredClone(base);
  next.files['agent.json'].models[1].name = 'changed';
  assert.deepEqual(requiredDebugComponents(next, base), ['backup']);
  next.files['agent.json'].prompt.template = 'after';
  assert.deepEqual(requiredDebugComponents(next, base), ['backup', 'primary']);
});

test('static tool body changes require every consuming model but metadata does not', () => {
  const base = {
    files: {
      'tool.json': {
        id: 'guide',
        kind: 'tool',
        static_result: { text: 'before' },
        description: 'guide',
      },
      'consumer.json': {
        models: [{ component_id: 'primary' }, { component_id: 'backup' }],
        tools: ['guide'],
      },
      'unrelated.json': { models: [{ component_id: 'judge' }], tools: [] },
    },
  };
  const next = structuredClone(base);
  next.files['tool.json'].description = 'new description';
  assert.deepEqual(requiredDebugComponents(next, base), []);
  next.files['tool.json'].static_result.text = 'after';
  assert.deepEqual(requiredDebugComponents(next, base), ['backup', 'primary']);
});
