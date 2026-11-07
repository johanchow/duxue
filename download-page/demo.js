(function (root) {
  'use strict';
  function startDemo(win) {
    const doc = win.document;
    const video = doc.getElementById('product-demo');
    if (!video) return;
    const links = Array.from(doc.querySelectorAll('[data-demo-start]'));
    const status = doc.getElementById('demo-status');
    let pending = null;
    function seek() {
      if (pending === null || video.readyState < 1) return;
      const end = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.05) : pending;
      video.currentTime = Math.min(pending, end);
      pending = null;
    }
    function selected() {
      const starts = [...new Set(links.map(link => Number(link.dataset.demoStart)))].sort((a, b) => a - b);
      const active = starts.filter(start => start <= video.currentTime + 0.1).pop() ?? starts[0];
      links.forEach(link => link.setAttribute(link.tagName === 'A' ? 'aria-current' : 'aria-pressed', String(Number(link.dataset.demoStart) === active)));
    }
    links.forEach(link => link.addEventListener('click', () => {
      const time = Number(link.dataset.demoStart);
      if (!Number.isFinite(time) || time < 0) return;
      pending = time;
      status.textContent = '';
      seek();
      const playing = video.play();
      if (playing && typeof playing.catch === 'function') {
        playing.catch(() => { status.textContent = '点击播放器中的播放按钮即可观看。'; });
      }
    }));
    video.addEventListener('loadedmetadata', seek);
    video.addEventListener('timeupdate', selected);
    video.addEventListener('error', () => { status.textContent = '演示视频暂时无法加载，请稍后重试。'; });
    selected();
  }
  if (typeof module === 'object' && module.exports) module.exports = { startDemo };
  else startDemo(root);
})(typeof window === 'object' ? window : globalThis);
