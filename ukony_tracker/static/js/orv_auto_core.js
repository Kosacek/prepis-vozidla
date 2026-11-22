// Hands-free capture of a document held in front of the camera — the pure part.
//
// No DOM, no timers, no app names: feed `step()` one sample per analysed frame
// and it says when to take the photo. Žádosti copies this file verbatim.
//
// A sample is {t (ms), motion, sharp, edges, sig, qr, qrT}:
//   motion  mean absolute grey difference to the previous analysed frame (0–255)
//   sharp   variance of the Laplacian inside the guide (focus / blur)
//   edges   share of strong-gradient pixels inside the guide (printed card vs. bare desk)
//   sig     coarse grey signature of the frame (`signature()`), to tell scenes apart
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
    steadyMotion: 6,    // at or below: the frame is still (hand tremor included)
    enterMotion: 14,    // above: something moved in the picture
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

  // -- Decision --------------------------------------------------------------
  // One photo per card. After a photo nothing fires until the scene clearly
  // changes: the guide goes empty, the idle background comes back, a new still
  // scene unlike the photographed one, or a different QR. The same QR never
  // fires twice in a row. Without a QR, a still scene must also differ from
  // the idle background, so a hand passing over a textured desk fires nothing.
  function create(options) {
    const p = Object.assign({}, DEFAULTS, options || {});
    let s;
    function reset() {
      s = {captured: false, entered: false, lastQr: null, ref: null, bg: null, lastFire: -Infinity,
        stillSince: null, goodSince: null, emptySince: null, newSince: null,
        recentQr: null, recentQrT: -Infinity, reserved: null, photoId: null, lastSig: null, lastT: 0};
    }
    function since(key, on, t) { s[key] = on ? (s[key] == null ? t : s[key]) : null; }
    const differs = (a, b) => !!a && !!b && sigDiff(a, b) >= p.sceneDiff;

    function rearm(x, t, qr, still) {
      since('emptySince', x.edges < p.emptyEdge, t);
      since('newSince', still && differs(x.sig, s.ref), t);
      const otherQr = !!qr && !!s.lastQr && qr !== s.lastQr;
      const empty = s.emptySince != null && t - s.emptySince >= p.rearmMs;
      const fresh = s.newSince != null && t - s.newSince >= p.rearmMs;
      if (!otherQr && !empty && !fresh) return null;
      s.captured = false;
      s.emptySince = s.newSince = null;
      if (otherQr) return 'jiny-qr';
      // The idle background again counts as an empty guide.
      const background = fresh && s.bg && !differs(x.sig, s.bg);
      if (empty || background) { s.entered = false; return 'prazdno'; }
      s.entered = true; // a new card replaced the photographed one in one move
      return 'nova-scena';
    }
    function lock(t, sig, qr, photoId) {
      s.captured = true;
      s.ref = sig || null;
      s.lastQr = qr || null;
      s.lastFire = t;
      s.entered = false;
      s.stillSince = s.goodSince = null;
      s.photoId = photoId == null ? null : photoId;
    }
    function fire(x, t, reason, qr) {
      s.reserved = {lastQr: s.lastQr, ref: s.ref, entered: s.entered, photoId: s.photoId};
      lock(t, x.sig, qr, null);
      return {fire: true, reason, qr: qr || null, armed: false, locked: true, progress: 1, rearmed: null};
    }
    function step(x) {
      const t = +x.t;
      const m = typeof x.motion === 'number' ? x.motion : null;
      const still = m != null && m <= p.steadyMotion;
      if (m != null && m > p.enterMotion) { s.entered = true; s.recentQr = null; }
      since('stillSince', still, t);
      // A QR counts only when it was read in the current still spell: a read
      // from before the card moved must never ride along with the next card.
      const read = cleanQr(x.qr);
      const readT = typeof x.qrT === 'number' ? x.qrT : t;
      if (read && s.stillSince != null && readT >= s.stillSince) { s.recentQr = read; s.recentQrT = readT; }
      const qr = s.recentQr && s.stillSince != null && s.recentQrT >= s.stillSince &&
        t - s.recentQrT <= p.qrMemoryMs ? s.recentQr : null;
      const sharp = x.sharp >= p.sharpMin;
      const card = x.edges >= p.edgeMin;
      since('goodSince', still && sharp && card, t);
      // Learn the idle background: a still scene while nothing has moved in,
      // and at start the first scene held still (raising the phone counts as
      // movement, and the desk it then looks at must not fire). A card already
      // held up when the camera opens becomes the background: it needs the
      // shutter or a QR, never a guess.
      if (!s.captured && still && x.sig && t - s.stillSince >= p.rearmMs && (!s.entered || !s.bg)) s.bg = x.sig;
      s.lastSig = x.sig || s.lastSig;
      s.lastT = t;
      const rearmed = s.captured && !s.reserved ? rearm(x, t, qr, still) : null;
      const base = {fire: false, reason: null, qr, armed: !s.captured, locked: false, progress: 0, rearmed};
      if (s.captured || t - s.lastFire < p.cooldownMs) return base;
      if (qr) {
        if (qr === s.lastQr) return base; // the same card again: never automatic
        const held = s.stillSince == null ? 0 : t - s.stillSince;
        const ready = still && x.sharp >= p.sharpMin * 0.7;
        if (ready && held >= p.qrHoldMs) return fire(x, t, 'qr', qr);
        return Object.assign(base, {locked: ready, progress: ready ? Math.min(1, held / p.qrHoldMs) : 0});
      }
      const held = s.goodSince == null ? 0 : t - s.goodSince;
      const locked = s.entered && s.goodSince != null && (!s.bg || differs(x.sig, s.bg));
      if (locked && held >= p.holdMs) return fire(x, t, 'klid', null);
      return Object.assign(base, {locked, progress: locked ? Math.min(1, held / p.holdMs) : 0});
    }
    // The reserved photo is in the batch.
    function commit(photoId) {
      if (!s.reserved) return;
      s.reserved = null;
      s.photoId = photoId == null ? null : photoId;
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
      lock(s.lastT, s.lastSig, cleanQr(qr), photoId);
    }
    // The latest photo was removed from the batch: its card may be taken again,
    // even while it is still held in front of the camera.
    function forget(photoId) {
      if (photoId == null || photoId !== s.photoId || s.reserved) return;
      s.captured = false;
      s.lastQr = s.ref = s.photoId = null;
      s.entered = true;
      s.stillSince = s.goodSince = null;
    }
    reset();
    return {step, reset, commit, release, manual, forget, params: Object.freeze(Object.assign({}, p))};
  }

  const api = {DEFAULTS, cleanQr, gray, motion, sharpness, edges, signature, sigDiff, create};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvAutoCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
