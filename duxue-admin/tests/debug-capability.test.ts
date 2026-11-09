import test from 'node:test';
import assert from 'node:assert/strict';
import { debugCapability } from '../src/lib/debug-capability';
const bundle = {
  files: {
    agent: {
      id: 'tutoring.turn',
      kind: 'agent',
      models: [{}],
      tools: ['tool'],
    },
    gate: { id: 'guard', kind: 'gate', implementation: 'code' },
    tool: { id: 'tool', kind: 'tool' },
    flow: {
      id: 'tutoring',
      kind: 'workflow',
      nodes: [{ ref: 'tutoring.turn' }, { ref: 'guard' }],
    },
    planning: {
      id: 'planning.session-turn',
      kind: 'agent',
      implementation: 'code',
      handler_id: 'planning',
    },
  },
};
const capabilities = {
  workflows: ['tutoring'],
  limitations: { planning: '依赖计划检查点' },
};
test('debug availability explains code gates/tools and points to a real containing workflow', () => {
  assert.equal(
    debugCapability(
      { kind: 'agent', id: 'tutoring.turn' },
      bundle,
      capabilities,
    ).supported,
    true,
  );
  const gate = debugCapability(
    { kind: 'agent', id: 'guard' },
    bundle,
    capabilities,
  );
  assert.equal(gate.supported, false);
  assert.equal(gate.workflowId, 'tutoring');
  assert(gate.reason.includes('代码门禁'));
  const tool = debugCapability(
    { kind: 'agent', id: 'tool' },
    bundle,
    capabilities,
  );
  assert.equal(tool.workflowId, 'tutoring');
  assert(tool.reason.includes('调用方'));
  assert.equal(
    debugCapability(
      { kind: 'agent', id: 'planning.session-turn' },
      bundle,
      capabilities,
    ).reason,
    '依赖计划检查点',
  );
  assert.equal(
    debugCapability({ kind: 'workflow', id: 'missing' }, bundle, capabilities)
      .supported,
    false,
  );
  const fixed = debugCapability(
    { kind: 'agent', id: 'tool' },
    {
      files: {
        ...bundle.files,
        tool: { ...bundle.files.tool, handler_id: 'tool.static_result' },
      },
    },
    capabilities,
  );
  assert(fixed.reason.includes('固定正文'));
});
