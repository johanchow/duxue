const { test } = require('node:test');
const assert = require('node:assert/strict');
const { startDemo } = require('./demo.js');
function fixture(readyState = 1, reject = false) {
  const video = { readyState, duration: 74, currentTime: 0, events: {}, plays: 0,
    addEventListener(name, fn) { this.events[name] = fn; },
    play() { this.plays++; return reject ? Promise.reject(new Error('blocked')) : Promise.resolve(); },
  };
  const links = [2, 16, 26, 50].map(time => ({ dataset: { demoStart: String(time) }, attrs: {},
    addEventListener(name, fn) { this[name] = fn; }, setAttribute(name, value) { this.attrs[name] = value; },
  }));
  const status = { textContent: '' };
  startDemo({ document: { getElementById: id => id === 'product-demo' ? video : status, querySelectorAll: () => links } });
  return { video, links, status };
}
test('each chapter starts the corresponding part of the actual video', async () => {
  const f = fixture();
  f.links[3].click();
  assert.equal(f.video.currentTime, 50);
  assert.equal(f.video.plays, 1);
  f.video.events.timeupdate();
  assert.equal(f.links[3].attrs['aria-pressed'], 'true');
  assert.equal(f.links[0].attrs['aria-pressed'], 'false');
});
test('before metadata loads the most recent chapter choice wins', () => {
  const f = fixture(0);
  f.links[1].click(); f.links[2].click();
  assert.equal(f.video.currentTime, 0);
  f.video.readyState = 1; f.video.events.loadedmetadata();
  assert.equal(f.video.currentTime, 26);
});
test('blocked playback exposes a usable native-player fallback', async () => {
  const f = fixture(1, true);
  f.links[1].click(); await Promise.resolve();
  assert.equal(f.video.currentTime, 16);
  assert.equal(f.status.textContent, '点击播放器中的播放按钮即可观看。');
});
test('media failure is reported and out-of-range seeking is bounded', () => {
  const f = fixture(); f.video.duration = 40; f.links[3].click();
  assert.ok(f.video.currentTime < 40);
  f.video.events.error();
  assert.equal(f.status.textContent, '演示视频暂时无法加载，请稍后重试。');
});
