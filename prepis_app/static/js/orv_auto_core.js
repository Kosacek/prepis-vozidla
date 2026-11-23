// Hands-free capture of a document held in front of the camera — the pure part.
//
// No DOM, no timers, no app names: feed `step()` one sample per analysed frame
// and it says when to take the photo. Žádosti copies this file verbatim.
//
// A sample is {t (ms), motion, sharp, edges, sig, quad, cardSig, qr, qrT}:
//   motion  mean absolute grey difference to the previous analysed frame (0–255)
//   sharp   variance of the Laplacian inside the guide (focus / blur)
//   edges   share of strong-gradient pixels inside the guide (printed card vs. bare desk)
//   sig     coarse grey signature of the frame (`signature()`), to tell scenes apart
//   quad    four cyclically ordered corners in fractions of the frame, or null
//   cardSig coarse signature sampled inside the quad, independent of its position
//   qr      an ORV number decoded from a QR in the guide, or null
//   qrT     time of the frame that QR was decoded from (defaults to t)
//
// A photo is reserved when step() fires. The app then either commit(photoId)s
// it (the photo is in the batch) or release()s it (the photo failed), so a
// failed shot can be retried. A manual shot is reported with manual(photoId).
(function (root) {
  const ORV = /^[A-Z]{3}[0-9]{6}$/;

  // Every misfire costs a Haiku read and a "nečitelné" card, so these lean
  // conservative. Tune them from the logged values on a real phone.
  const DEFAULTS = Object.freeze({
    steadyMotion: 18,   // fallback when corners are unavailable
    enterMotion: 35,    // large change in a scene without a quad
    quadMotion: 0.025, // maximum corner displacement from the start of a hold
    requireQuad: false, // phones opt in; fixed cameras can use the empty desk
    sharpMin: 90,       // Laplacian variance that counts as in focus
    edgeMin: 0.045,     // printed card inside the guide
    emptyEdge: 0.02,    // below: the guide is empty (card taken away)
    qrHoldMs: 250,      // still this long with a new QR → photo
    holdMs: 1300,       // still + sharp + card-like this long without QR → photo
    qrMemoryMs: 1000,   // a QR read in this still spell counts this long (decoding flickers)
    sceneDiff: 16,      // signature difference that makes two scenes different
    rearmMs: 250,       // empty guide or a new still scene this long re-arms
    cooldownMs: 1200,   // minimum gap between two automatic photos
  });

  // Exactly an ORV number. No trimming: the server gets the same exact value.
  function cleanQr(value) {
    return typeof value === 'string' && ORV.test(value) ? value : null;
  }

  // -- Frame metrics (grey Uint8Array, row-major, width w) -------------------
  function gray(rgba, w, h) {
    const out = new Uint8Array(w * h);
    for (let i = 0, j = 0; i < out.length; i++, j += 4) {
      out[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8;
    }
    return out;
  }
  function motion(prev, cur) {
    if (!prev || !cur || prev.length !== cur.length || !cur.length) return null;
    let sum = 0;
    for (let i = 0; i < cur.length; i++) sum += Math.abs(cur[i] - prev[i]);
    return sum / cur.length;
  }
  function box(w, h, rect) {
    const r = rect || {x: 0, y: 0, w: 1, h: 1};
    const x0 = Math.max(1, Math.floor(r.x * w)), y0 = Math.max(1, Math.floor(r.y * h));
    const x1 = Math.min(w - 1, Math.ceil((r.x + r.w) * w)), y1 = Math.min(h - 1, Math.ceil((r.y + r.h) * h));
    return {x0, y0, x1, y1};
  }
  // Focus: variance of the 4-neighbour Laplacian. Blur flattens it.
  function sharpness(g, w, h, rect) {
    const b = box(w, h, rect);
    let n = 0, sum = 0, sq = 0;
    for (let y = b.y0; y < b.y1; y++) {
      for (let x = b.x0; x < b.x1; x++) {
        const i = y * w + x;
        const v = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w];
        sum += v; sq += v * v; n++;
      }
    }
    if (!n) return 0;
    const mean = sum / n;
    return sq / n - mean * mean;
  }
  // Print on a card gives many strong gradients; a plain desk or a palm few.
  function edges(g, w, h, rect, threshold) {
    const b = box(w, h, rect), limit = threshold || 48;
    let n = 0, hit = 0;
    for (let y = b.y0; y < b.y1; y++) {
      for (let x = b.x0; x < b.x1; x++) {
        const i = y * w + x;
        if (Math.abs(g[i + 1] - g[i - 1]) + Math.abs(g[i + w] - g[i - w]) > limit) hit++;
        n++;
      }
    }
    return n ? hit / n : 0;
  }
  function signature(g, w, h, cols, rows) {
    const cx = cols || 16, cy = rows || 9, out = new Array(cx * cy).fill(0), cnt = new Array(cx * cy).fill(0);
    for (let y = 0; y < h; y++) {
      const row = Math.min(cy - 1, Math.floor(y * cy / h));
      for (let x = 0; x < w; x++) {
        const k = row * cx + Math.min(cx - 1, Math.floor(x * cx / w));
        out[k] += g[y * w + x]; cnt[k]++;
      }
    }
    return out.map((v, k) => cnt[k] ? v / cnt[k] : 0);
  }
  function sigDiff(a, b) {
    if (!a || !b || a.length !== b.length || !a.length) return Infinity;
    let sum = 0;
    for (let i = 0; i < a.length; i++) sum += Math.abs(a[i] - b[i]);
    return sum / a.length;
  }

  function cardSignature(g, w, h, quad) {
    const [a, b, c, d] = quad;
    const out = [];
    for (let row = 1; row <= 9; row++) {
      const v = row / 10;
      for (let col = 1; col <= 16; col++) {
        const u = col / 17;
        const x = (1 - v) * ((1 - u) * a[0] + u * b[0]) + v * ((1 - u) * d[0] + u * c[0]);
        const y = (1 - v) * ((1 - u) * a[1] + u * b[1]) + v * ((1 - u) * d[1] + u * c[1]);
        const px = Math.max(2, Math.min(w - 3, Math.round(x * w)));
        const py = Math.max(2, Math.min(h - 3, Math.round(y * h)));
        let sum = 0;
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) sum += g[(py + dy) * w + px + dx];
        }
        out.push(sum / 25);
      }
    }
    return out;
  }

  function nearby(a, b, limit) {
    // The detector's first corner can change when the card is diagonal.
    return a.some((_, shift) => a.every(([x, y], k) => {
      const [bx, by] = b[(k + shift) % 4];
      return Math.hypot(x - bx, y - by) <= limit;
    }));
  }

  // -- Decision --------------------------------------------------------------
  // One photo per card. After a photo nothing fires until the scene clearly
  // changes: the quad leaves, a different card settles in view, or a different
  // QR appears. A fixed camera can also re-arm against its learned idle scene.
  function create(options) {
    const p = Object.assign({}, DEFAULTS, options || {});
    let s;
    function reset() {
      s = {captured: false, entered: false, lastQr: null, photoQrs: new Map(), ref: null, bg: null, lastFire: -Infinity,
        quadAnchor: null,
        stillSince: null, goodSince: null, emptySince: null, newSince: null,
        recentQr: null, recentQrT: -Infinity, reserved: null, photoId: null, lastFrame: null};
    }
    function since(key, on, t) { s[key] = on ? (s[key] == null ? t : s[key]) : null; }
    const differs = (a, b) => !!a && !!b && sigDiff(a, b) >= p.sceneDiff;
    function seen(qr) {
      for (const value of s.photoQrs.values()) if (value === qr) return true;
      return false;
    }

    function rearm(x, t, qr, still) {
      since('emptySince', s.ref?.quad ? !x.quad : !x.quad && x.edges < p.emptyEdge, t);
      const newScene = s.ref?.quad
        ? x.quad && differs(x.cardSig, s.ref.cardSig)
        : differs(x.sig, s.ref?.sig);
      since('newSince', still && newScene, t);
      const otherQr = !!qr && !!s.lastQr && qr !== s.lastQr && !seen(qr);
      const empty = s.emptySince != null && t - s.emptySince >= p.rearmMs;
      const fresh = s.newSince != null && t - s.newSince >= p.rearmMs;
      if (!otherQr && !empty && !fresh) return null;
      s.captured = false;
      s.emptySince = s.newSince = null;
      if (otherQr) return 'jiny-qr';
      // The idle background again counts as an empty guide.
      const background = fresh && !x.quad && s.bg && !differs(x.sig, s.bg);
      if (empty || background) { s.entered = false; return 'prazdno'; }
      s.entered = true; // a new card replaced the photographed one in one move
      return 'nova-scena';
    }
    function lock(x, qr, photoId) {
      s.captured = true;
      s.ref = x;
      s.lastQr = qr || null;
      s.lastFire = x?.t ?? 0;
      s.entered = false;
      s.stillSince = s.goodSince = s.emptySince = s.newSince = null;
      s.photoId = photoId == null ? null : photoId;
    }
    function fire(x, reason, qr) {
      s.reserved = {lastQr: s.lastQr, ref: s.ref, photoId: s.photoId};
      lock(x, qr, null);
      return {fire: true, reason, qr: qr || null, armed: false, locked: true, stable: true, progress: 1, rearmed: null};
    }
    function step(x) {
      const t = +x.t;
      const m = typeof x.motion === 'number' ? x.motion : null;
      // A card can be swapped without changing the outline. Invalidate any
      // pending QR if both raw motion and the card's own content jump.
      const swapped = x.quad && m > p.enterMotion && differs(x.cardSig, s.lastFrame?.cardSig);
      const changed = swapped || !!x.quad !== !!s.quadAnchor ||
        (x.quad && s.quadAnchor && !nearby(x.quad, s.quadAnchor, p.quadMotion));
      if (changed || m == null) {
        s.quadAnchor = x.quad || null;
        s.stillSince = s.goodSince = s.newSince = s.recentQr = null;
      }
      const still = m != null && (x.quad ? !changed || !s.lastFrame?.quad : m <= p.steadyMotion);
      if (!x.quad && m != null && m > p.enterMotion) s.entered = true;
      since('stillSince', still, t);
      // A QR counts only when it was read in the current still spell: a read
      // from before the card moved must never ride along with the next card.
      const read = cleanQr(x.qr);
      const readT = typeof x.qrT === 'number' ? x.qrT : t;
      if (read && s.stillSince != null && readT >= s.stillSince) { s.recentQr = read; s.recentQrT = readT; }
      const qr = s.recentQr && s.stillSince != null && s.recentQrT >= s.stillSince &&
        t - s.recentQrT <= p.qrMemoryMs ? s.recentQr : null;
      const sharp = x.sharp >= p.sharpMin;
      const edges = x.edges >= p.edgeMin;
      const card = !!x.quad || (!p.requireQuad && s.entered && !!s.bg && differs(x.sig, s.bg));
      since('goodSince', still && sharp && edges && card, t);
      // Only the fixed-camera fallback learns an idle background.
      if (!p.requireQuad && !x.quad && !s.captured && still && x.sig &&
          t - s.stillSince >= p.rearmMs && (!s.entered || !s.bg)) s.bg = x.sig;
      s.lastFrame = x;
      const rearmed = s.captured && !s.reserved ? rearm(x, t, qr, still) : null;
      const base = {fire: false, reason: null, qr, armed: !s.captured, locked: false, stable: still, progress: 0, rearmed};
      if (s.captured) return {...base, reason: 'captured'};
      if (t - s.lastFire < p.cooldownMs) return {...base, reason: 'cooldown'};
      if (!still) return {...base, reason: 'moving'};
      if (p.requireQuad && !x.quad) return {...base, reason: 'no-quad'};
      if (qr) {
        if (seen(qr)) return {...base, reason: 'same-qr'};
        if (x.sharp < (x.quad ? p.sharpMin : p.sharpMin * 0.7)) return {...base, reason: 'blur'};
        if (x.quad && !edges) return {...base, reason: 'few-edges'};
        const held = t - (x.quad ? s.goodSince : s.stillSince);
        if (held >= p.qrHoldMs) return fire(x, 'qr', qr);
        return {...base, reason: 'qr-hold', locked: true, progress: held / p.qrHoldMs};
      }
      if (!sharp) return {...base, reason: 'blur'};
      if (!edges) return {...base, reason: 'few-edges'};
      if (s.goodSince == null) return {...base, reason: 'idle-scene'};
      const held = t - s.goodSince;
      if (held >= p.holdMs) return fire(x, 'klid', null);
      return {...base, reason: 'hold', locked: true, progress: held / p.holdMs};
    }
    // The reserved photo is in the batch.
    function commit(photoId, qr) {
      if (!s.reserved) return;
      s.reserved = null;
      s.photoId = photoId == null ? null : photoId;
      s.lastQr = cleanQr(qr) || s.lastQr;
      if (s.lastQr) s.photoQrs.set(s.photoId, s.lastQr);
    }
    // The reserved photo failed: the same card may fire again after the cooldown.
    function release() {
      if (!s.reserved) return;
      const r = s.reserved;
      s.reserved = null;
      s.captured = false;
      s.lastQr = r.lastQr; s.ref = r.ref; s.photoId = r.photoId;
      s.entered = true;
      s.stillSince = s.goodSince = null;
    }
    // A manual shot of the scene in front: no automatic duplicate of it.
    function manual(photoId, qr) {
      if (s.reserved) return;
      lock(s.lastFrame, cleanQr(qr), photoId);
      if (s.lastQr) s.photoQrs.set(s.photoId, s.lastQr);
    }
    // The latest photo was removed from the batch: its card may be taken again,
    // even while it is still held in front of the camera.
    function forget(photoId) {
      if (photoId == null) return;
      s.photoQrs.delete(photoId);
      if (photoId !== s.photoId || s.reserved) return;
      s.captured = false;
      s.lastQr = s.ref = s.photoId = null;
      s.entered = true;
      s.stillSince = s.goodSince = null;
    }
    reset();
    return {step, reset, commit, release, manual, forget, params: Object.freeze(Object.assign({}, p))};
  }

  const api = {DEFAULTS, cleanQr, gray, motion, sharpness, edges, signature, cardSignature, sigDiff, create};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvAutoCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
