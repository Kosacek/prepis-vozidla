// Hands-free capture driver: watches a <video>, decides with OrvAutoCore and
// reads the QR with OrvQr. No app DOM: žádosti copies this file verbatim.
//
// OrvAuto.create({
//   video,                  the live <video>
//   crop(),                 visible part of the video in video pixels {x, y, w, h}
//   guide,                  card area as fractions of the visible part (default 8 % / 6 % inset)
//   canFire(),              false while the app cannot take a photo (busy, batch full)
//   onFire(info),           take the photo now; info.reason 'qr' | 'klid'
//   onTick(info),           every analysed frame (lock / progress for the UI)
//   params, fps, qrFps, jsqrUrl, debug
// })
// After onFire the app calls commit(photoId) or release(); after a manual
// shot manual(photoId, qr); when a photo leaves the batch forget(photoId).
// verify(canvas, w, h) reads the QR from the photo itself before upload.
(function (root) {
  const C = root.OrvAutoCore;
  const WIDTH = 160;          // analysed copy of the frame, px

  function num(value, digits, max) {
    const v = typeof value === 'number' && isFinite(value) ? Math.max(0, Math.min(max, value)) : 0;
    return v.toFixed(digits);
  }
  // Short, fixed-shape description of a capture for the server log.
  function zachyt(reason, info) {
    const i = info || {};
    return [reason, 'm=' + num(i.motion, 1, 9999), 's=' + num(i.sharp, 0, 99999),
      'e=' + num(i.edges, 3, 1)].join(' ');
  }

  function create(o) {
    const core = C.create(o.params);
    const p = core.params;
    const qr = root.OrvQr ? root.OrvQr.create({jsqrUrl: o.jsqrUrl, guide: o.guide}) : null;
    const guide = o.guide || {x: 0.08, y: 0.06, w: 0.84, h: 0.88};
    const period = 1000 / (o.fps || 8), qrPeriod = 1000 / (o.qrFps || 4);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', {willReadFrequently: true});
    let timer = null, running = false, enabled = true, prev = null, armed = true;
    // A QR read belongs to the frame it was taken from; any real movement
    // after that frame (qrGen++) throws the read away when it arrives.
    let qrGen = 0, qrTry = -Infinity, qrResult = null, lastLog = -Infinity;
    const clock = () => (root.performance && root.performance.now ? root.performance.now() : Date.now());

    function log(kind, info) {
      if (!root.console) return;
      const line = (info.reason ? info.reason + ' ' : '') + zachyt('', info).trim() +
        (info.qr ? ' qr=' + info.qr : '');
      (kind === 'tick' ? root.console.debug : root.console.info).call(root.console, '[orv-auto] ' + kind + ' ' + line);
    }
    function readQr(v, crop, t, m) {
      if (!qr || m == null || m > p.steadyMotion * 2) return; // only a steady picture is worth it
      if (t - qrTry < (armed ? qrPeriod : 1000)) return;
      qrTry = t;
      const gen = qrGen;
      qr.decode(v, crop).then(value => {
        if (value && gen === qrGen && running) qrResult = {value, t};
      }, () => {});
    }
    function frame() {
      const v = o.video;
      if (!enabled || !v || v.readyState < 2 || !v.videoWidth || (o.canFire && !o.canFire())) {
        prev = null;
        return;
      }
      const crop = o.crop();
      if (!crop || crop.w < 2 || crop.h < 2) return;
      const h = Math.max(1, Math.round(WIDTH * crop.h / crop.w));
      if (canvas.width !== WIDTH || canvas.height !== h) { canvas.width = WIDTH; canvas.height = h; prev = null; }
      ctx.drawImage(v, crop.x, crop.y, crop.w, crop.h, 0, 0, WIDTH, h);
      const g = C.gray(ctx.getImageData(0, 0, WIDTH, h).data, WIDTH, h);
      const t = clock();
      const m = C.motion(prev, g);
      prev = g;
      if (m == null || m > p.enterMotion) { qrGen++; qrResult = null; }
      const found = qrResult;
      qrResult = null;
      const sample = {t, motion: m, sharp: C.sharpness(g, WIDTH, h, guide), edges: C.edges(g, WIDTH, h, guide),
        sig: C.signature(g, WIDTH, h), qr: found ? found.value : null, qrT: found ? found.t : t};
      readQr(v, crop, t, m);
      const out = core.step(sample);
      armed = out.armed;
      const info = Object.assign({}, out, {motion: m, sharp: sample.sharp, edges: sample.edges, t});
      if (o.onTick) o.onTick(info);
      if (out.rearmed) log('rearm ' + out.rearmed, info);
      if (o.debug && t - lastLog >= 1000) { lastLog = t; log('tick', info); }
      if (out.fire) {
        log('fire', info);
        o.onFire(Object.assign(info, {zachyt: zachyt(out.reason, info)}));
      }
    }
    function tick() {
      timer = null;
      if (!running) return;
      try { frame(); } catch (_) { prev = null; } // never break the camera
      if (running) timer = setTimeout(tick, period);
    }
    function start() {
      if (running) return;
      running = true;
      prev = null;
      core.reset(); // a restarted camera looks at a new scene: learn it afresh
      if (qr) qr.prepare();
      timer = setTimeout(tick, period);
    }
    function stop() {
      running = false;
      if (timer) clearTimeout(timer);
      timer = null;
      prev = null;
      qrGen++;
      qrResult = null;
    }
    function setEnabled(on) {
      enabled = !!on;
      prev = null;
      qrGen++;
      if (!enabled) core.reset();
    }
    return {
      start, stop, setEnabled,
      isEnabled: () => enabled,
      commit: id => core.commit(id),
      release: () => core.release(),
      // Only while the auto-capture watches: otherwise there is no scene to lock.
      manual: (id, value) => { if (enabled && running) core.manual(id, value); },
      forget: id => core.forget(id),
      verify: (source, width, height) => (qr ? qr.verify(source, width, height) : Promise.resolve(null)),
      qrKind: () => (qr ? qr.kind() : 'none'),
      zachyt,
    };
  }

  const api = {create, zachyt};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvAuto = api;
})(typeof window !== 'undefined' ? window : globalThis);
