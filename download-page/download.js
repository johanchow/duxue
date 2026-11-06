/* Device checks concern browser protocol identifiers, never user semantics. */
(function (root) {
  'use strict';
  function environment(ua, platform, touchPoints) {
    return {
      weixin: /MicroMessenger/i.test(ua),
      android: /Android/i.test(ua),
      ios: /iPhone|iPad|iPod/i.test(ua) || (platform === 'MacIntel' && touchPoints > 1),
      harmony: /OpenHarmony|ArkWeb/i.test(ua),
    };
  }
  function releaseFrom(data, origin) {
    const r = data && data.android;
    if (!r) return null;
    const url = new URL(r.url, origin);
    if (url.origin !== origin || !url.pathname.startsWith('/releases/android/') ||
        !url.pathname.endsWith('.apk') || url.search || url.hash ||
        typeof r.version !== 'string' || !r.version ||
        !Number.isSafeInteger(r.build) || r.build < 1 ||
        !Number.isSafeInteger(r.size) || r.size < 1) {
      throw new Error('Invalid release metadata');
    }
    return { ...r, url: url.href };
  }
  async function start(win) {
    const doc = win.document;
    const get = id => doc.getElementById(id);
    const env = environment(win.navigator.userAgent, win.navigator.platform, win.navigator.maxTouchPoints);
    const button = get('android'), label = get('download-label'), status = get('status');
    let release = null, timer = null, loading = false, autoAttempted = false;
    function showGuide() {
      get('weixin').hidden = false;
      get('close-weixin').focus();
    }
    function closeGuide() {
      get('weixin').hidden = true;
      button.focus();
    }
    get('close-weixin').addEventListener('click', closeGuide);
    doc.addEventListener('keydown', event => {
      if (get('weixin').hidden) return;
      if (event.key === 'Escape') closeGuide();
      if (event.key === 'Tab') { event.preventDefault(); get('close-weixin').focus(); }
    });
    button.addEventListener('click', event => {
      if (timer !== null) { win.clearTimeout(timer); timer = null; }
      if (!release) { event.preventDefault(); return; }
      if (env.weixin) { event.preventDefault(); showGuide(); }
    });
    if (env.weixin && !env.ios) showGuide();
    async function load() {
      if (loading) return;
      loading = true;
      get('retry').hidden = true;
      status.textContent = '正在检查可下载的版本。';
      const controller = new win.AbortController();
      const timeout = win.setTimeout(() => controller.abort(), 10000);
      try {
        const response = await win.fetch('/latest.json', { cache: 'no-store', signal: controller.signal });
        if (response.status === 404) release = null;
        else {
          if (!response.ok) throw new Error('Release unavailable');
          release = releaseFrom(await response.json(), win.location.origin);
        }
        if (!release) {
          label.textContent = 'Android 版即将开放';
          status.textContent = '首个安装包正在准备中，请稍后再来。';
          get('retry').hidden = false;
          return;
        }
        button.href = release.url;
        button.removeAttribute('aria-disabled');
        button.removeAttribute('tabindex');
        label.textContent = '下载 Android 版';
        get('version').textContent = `版本 ${release.version} · Build ${release.build} · ${(release.size / 1024 / 1024).toFixed(1)} MB`;
        get('version').hidden = false;
        status.textContent = env.ios ? '当前安装包适用于 Android，iOS 版暂未开放。' :
          env.weixin ? '请在手机浏览器中打开此页下载。' :
          env.harmony ? '此安装包适用于支持 Android 应用的设备。' :
          env.android ? '正在尝试开始下载；未开始时请点击上方按钮。' : '在 Android 手机上打开此页，或点击下载安装包。';
        if (env.android && !env.ios && !env.weixin && !env.harmony && !autoAttempted) {
          autoAttempted = true;
          timer = win.setTimeout(() => {
            timer = null;
            if (doc.visibilityState !== 'hidden') win.location.assign(release.url);
          }, 1000);
        }
      } catch (_) {
        label.textContent = '暂时无法获取下载地址';
        status.textContent = '网络暂时不可用，请重试。';
        get('retry').hidden = false;
      } finally {
        win.clearTimeout(timeout);
        loading = false;
      }
    }
    get('retry').addEventListener('click', load);
    return load();
  }
  if (typeof module === 'object' && module.exports) module.exports = { environment, releaseFrom, start };
  else start(root);
})(typeof window === 'object' ? window : globalThis);
