import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AgentDebugActions } from '../src/components/agent-debug-actions';

const props = {
  capability: { supported: true, reason: '', workflowId: undefined },
  catalogSource: 'admin-draft',
  sourceDraftId: 'saved-draft',
  hasRelease: true,
  editingDraftId: null,
  draftLoaded: false,
  busy: false,
  onPublishedDebug() {},
  onDraftDebug(_id: string) {},
  navigate(_url: string) {},
};

test('a draft-backed model detail offers saved-draft debug without entering edit mode', () => {
  const html = renderToStaticMarkup(createElement(AgentDebugActions, props));
  assert.match(html, /调试已保存草稿/);
  assert.doesNotMatch(html, /调试已发布配置/);
});

test('published details and saved draft editors keep their explicit debug source', () => {
  assert.match(
    renderToStaticMarkup(
      createElement(AgentDebugActions, {
        ...props,
        catalogSource: 'admin-release',
      }),
    ),
    /调试已发布配置/,
  );
  assert.match(
    renderToStaticMarkup(
      createElement(AgentDebugActions, {
        ...props,
        editingDraftId: 'saved-draft',
        draftLoaded: true,
      }),
    ),
    /调试已保存草稿/,
  );
  assert.doesNotMatch(
    renderToStaticMarkup(
      createElement(AgentDebugActions, {
        ...props,
        editingDraftId: 'saved-draft',
      }),
    ),
    /<button/,
  );
});

test('unsupported components explain the limitation and link to their workflow for either source', () => {
  for (const catalogSource of ['admin-draft', 'admin-release']) {
    const html = renderToStaticMarkup(
      createElement(AgentDebugActions, {
        ...props,
        catalogSource,
        capability: {
          supported: false,
          reason: '依赖流程上下文',
          workflowId: 'tutoring',
        },
      }),
    );
    assert.match(html, /未开放独立调试/);
    assert.match(html, /打开所属 Workflow/);
    assert.doesNotMatch(html, /调试已保存草稿|调试已发布配置/);
  }
});
