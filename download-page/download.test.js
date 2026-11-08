const { test } = require('node:test');
const assert = require('node:assert/strict');
const { environment, releaseFrom, start } = require('./download.js');

const origin = 'https://download.duxuelai.xyz';
const data = { android: { url: '/releases/android/app.apk', version: '0.2.0', build: 42, size: 20971520 } };
function page(ua = '', responses = [data], extra = {}) {
  const elements = {};
  for (const id of ['android', 'download-label', 'status', 'retry', 'weixin', 'close-weixin']) {
    elements[id] = {
      hidden: true, events: {}, attrs: {}, textContent: '', href: '',
      addEventListener(event, action) { this.events[event] = action; },
      removeAttribute(name) { delete this.attrs[name]; },
      focus() { elements.focus = id; },
    };
  }
  const timers = new Map(), navigations = [], requests = [];
  let nextTimer = 0;
  const win = {
    document: { getElementById: id => elements[id], addEventListener() {}, visibilityState: 'visible' },
    navigator: { userAgent: ua, ...extra },
    location: { origin, assign: url => navigations.push(url) },
    AbortController,
    setTimeout(fn, delay) { timers.set(++nextTimer, { fn, delay }); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    async fetch(url, options) {
      requests.push({ url, options });
      const value = responses.shift();
      if (value instanceof Error) throw value;
      return { ok: value !== 404, status: value === 404 ? 404 : 200, json: async () => value };
    },
  };
  return { win, elements, timers, navigations, requests };
}

test('device routing covers Android, WeChat, iPad desktop UA and Harmony', () => {
  assert.equal(environment('Android MicroMessenger', '', 0).weixin, true);
  assert.equal(environment('Android', '', 0).android, true);
  assert.equal(environment('Macintosh', 'MacIntel', 5).ios, true);
  assert.equal(environment('Macintosh', 'MacIntel', 0).ios, false);
  assert.equal(environment('OpenHarmony ArkWeb', '', 0).harmony, true);
});
test('metadata only permits versioned APKs on the same origin', () => {
  assert.equal(releaseFrom(data, origin).url, origin + data.android.url);
  assert.equal(releaseFrom({ android: null }, origin), null);
  for (const url of ['https://other.test/app.apk', 'javascript:alert(1)', '//other.test/app.apk', '/latest.apk', '/releases/android/../../x.apk', '/releases/android/a.apk?token=x']) {
    assert.throws(() => releaseFrom({ android: { ...data.android, url } }, origin));
  }
  assert.throws(() => releaseFrom({ android: { ...data.android, build: '42' } }, origin));
});
test('Android waits for a manual click before downloading', async () => {
  const p = page('Android');
  await start(p.win);
  assert.equal(p.elements.android.href, origin + data.android.url);
  assert.equal(p.elements.status.hidden, true);
  assert.equal(p.elements.status.textContent, '');
  assert.equal(p.requests[0].options.cache, 'no-store');
  assert.equal(p.timers.size, 0);
  p.elements.android.events.click({ preventDefault: () => assert.fail('manual download blocked') });
  assert.equal(p.timers.size, 0);
  assert.deepEqual(p.navigations, []);
});
test('Android loading and retry never navigate automatically, and the button uses fetched metadata', async () => {
  const next = { android: { ...data.android, url: '/releases/android/new-build.apk', build: 43 } };
  const p = page('Android', [new Error('network'), next]);
  await start(p.win);
  await p.elements.retry.events.click();
  for (const timer of Array.from(p.timers.values())) timer.fn();
  assert.deepEqual(p.navigations, []);
  assert.equal(p.elements.android.href, origin + next.android.url);
  p.elements.android.events.click({ preventDefault: () => assert.fail('manual download blocked') });
});
test('WeChat intercepts APK navigation and keeps guide accessible after closing', async () => {
  const p = page('Android MicroMessenger');
  await start(p.win);
  assert.equal(p.elements.weixin.hidden, false);
  assert.equal(p.timers.size, 0);
  p.elements['close-weixin'].events.click();
  assert.equal(p.elements.weixin.hidden, true);
  let blocked = false;
  p.elements.android.events.click({ preventDefault() { blocked = true; } });
  assert.equal(blocked, true);
  assert.equal(p.elements.weixin.hidden, false);
});
test('iOS, desktop and Harmony do not automatically download APKs', async () => {
  for (const ua of ['iPhone', 'Macintosh', 'Android OpenHarmony ArkWeb']) {
    const p = page(ua);
    await start(p.win);
    assert.equal(p.timers.size, 0);
    assert.deepEqual(p.navigations, []);
    assert.equal(p.elements.status.hidden, true);
    assert.equal(p.elements.status.textContent, '');
  }
});
test('first release missing has no broken download link', async () => {
  const p = page('Android', [404]);
  await start(p.win);
  assert.equal(p.elements.android.href, '');
  assert.match(p.elements['download-label'].textContent, /即将开放/);
  assert.equal(p.elements.status.hidden, false);
  assert.equal(p.elements.retry.hidden, false);
  let blocked = false;
  p.elements.android.events.click({ preventDefault() { blocked = true; } });
  assert.equal(blocked, true);
});
test('network failure can retry and then download the latest release', async () => {
  const p = page('Android', [new Error('network'), data]);
  await start(p.win);
  assert.equal(p.elements.retry.hidden, false);
  assert.equal(p.elements.status.hidden, false);
  assert.match(p.elements.status.textContent, /网络暂时不可用/);
  assert.equal(p.elements.android.href, '');
  await p.elements.retry.events.click();
  assert.equal(p.elements.android.href, origin + data.android.url);
  assert.equal(p.elements.retry.hidden, true);
  assert.equal(p.elements.status.hidden, true);
  assert.equal(p.elements.status.textContent, '');
});
test('malformed metadata fails closed and Android never navigates in either visibility state', async () => {
  const invalid = page('Android', [{ android: { ...data.android, url: 'https://bad.test/a.apk' } }]);
  await start(invalid.win);
  assert.equal(invalid.elements.android.href, '');
  for (const visibility of ['visible', 'hidden']) {
    const p = page('Android');
    p.win.document.visibilityState = visibility;
    await start(p.win);
    for (const timer of Array.from(p.timers.values())) timer.fn();
    assert.deepEqual(p.navigations, []);
  }
});
