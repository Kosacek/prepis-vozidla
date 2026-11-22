// Skutečné rohy karty v obraze kamery nad stolem (žádosti 1.37.1).
//
// Kamera nad stolem stojí, takže nejlevnější spolehlivá cesta je rozdíl proti
// prázdnému stolu (pozadí), ne hrany: na dřevěném stole by hrany splynuly se
// vzorem dřeva. Postup na zmenšeném snímku (~256 px): rozdíl proti pozadí →
// maska → otevření (šum pryč) → největší souvislá oblast → konvexní obal →
// čtyřúhelník (průměr obalu = úhlopříčka, nejvzdálenější body po stranách) →
// kontrola, že je to karta (vyplnění, poměr stran, velikost). Když karta
// nesedí, vrátí null — obrys se pak nekreslí, nikdy se nic nepředstírá.
// Žádné DOM ani časovače; testy v tests/test_orv_quad.cjs.
(function (root) {
  'use strict';
  const DEFAULTS = Object.freeze({
    diff: 30,          // rozdíl jasu proti pozadí, od kterého je pixel „karta"
    minArea: 0.05,     // nejmenší karta (podíl snímku)
    maxArea: 0.92,     // větší = změna světla nebo kamera viděla něco jiného
    minFill: 0.82,     // plocha oblasti / plocha čtyřúhelníku (ruka přes kartu = méně)
    minAspect: 1.2,    // ORV 85,6 × 54 mm = 1,59; perspektiva ho trochu mění
    maxAspect: 2.2,
    maxSkew: 18,       // kamera shora: rohy skoro pravé (°), ruka v záběru je zkřiví
    maxSideRatio: 1.3, // protilehlé strany skoro stejně dlouhé
  });

  function create(options) {
    const p = Object.assign({}, DEFAULTS, options || {});
    let bg = null, w = 0, h = 0, mask = null, tmp = null, labels = null, stack = null;

    function size(width, height) {
      if (width === w && height === h) return;
      w = width; h = height;
      mask = new Uint8Array(w * h); tmp = new Uint8Array(w * h);
      labels = new Int32Array(w * h); stack = new Int32Array(w * h);
      bg = null;
    }
    function setBackground(gray, width, height) {
      size(width, height);
      bg = Uint8Array.from(gray);
    }
    // Eroze a dilatace 3×3 (otevření): osamělé pixely šumu zmizí, karta zůstane.
    function morph(src, dst, erode) {
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          let v = erode ? 1 : 0;
          for (let dy = -1; dy <= 1 && (erode ? v : !v); dy++) {
            const yy = y + dy;
            if (yy < 0 || yy >= h) { if (erode) v = 0; continue; }
            for (let dx = -1; dx <= 1; dx++) {
              const xx = x + dx;
              const on = xx >= 0 && xx < w && src[yy * w + xx];
              if (erode && !on) { v = 0; break; }
              if (!erode && on) { v = 1; break; }
            }
          }
          dst[y * w + x] = v;
        }
      }
    }
    // Největší souvislá oblast (4-sousedství) → její hranice po řádcích.
    function largest() {
      labels.fill(0);
      let best = 0, bestCount = 0, label = 0;
      for (let i = 0; i < w * h; i++) {
        if (!mask[i] || labels[i]) continue;
        label++;
        let top = 0, count = 0;
        stack[top++] = i; labels[i] = label;
        while (top) {
          const j = stack[--top];
          count++;
          const x = j % w;
          if (x > 0 && mask[j - 1] && !labels[j - 1]) { labels[j - 1] = label; stack[top++] = j - 1; }
          if (x < w - 1 && mask[j + 1] && !labels[j + 1]) { labels[j + 1] = label; stack[top++] = j + 1; }
          if (j >= w && mask[j - w] && !labels[j - w]) { labels[j - w] = label; stack[top++] = j - w; }
          if (j < w * (h - 1) && mask[j + w] && !labels[j + w]) { labels[j + w] = label; stack[top++] = j + w; }
        }
        if (count > bestCount) { best = label; bestCount = count; }
      }
      if (!best) return null;
      const pts = [];
      for (let y = 0; y < h; y++) {
        let l = -1, r = -1;
        for (let x = 0; x < w; x++) if (labels[y * w + x] === best) { if (l < 0) l = x; r = x; }
        if (l >= 0) { pts.push([l, y], [r + 1, y], [l, y + 1], [r + 1, y + 1]); }
      }
      return {count: bestCount, pts};
    }

    function find(gray, width, height) {
      if (!bg || width !== w || height !== h) return null;
      for (let i = 0; i < w * h; i++) tmp[i] = Math.abs(gray[i] - bg[i]) > p.diff ? 1 : 0;
      morph(tmp, mask, true);
      morph(mask, tmp, false);
      mask.set(tmp);
      const blob = largest();
      if (!blob || blob.count < p.minArea * w * h) return null;
      const quad = quadOf(hull(blob.pts));
      if (!quad) return null;
      const area = polyArea(quad);
      const fill = blob.count / area;
      const sides = [0, 1, 2, 3].map(k => dist(quad[k], quad[(k + 1) % 4]));
      const long = (sides[0] + sides[2]) / 2, short = (sides[1] + sides[3]) / 2;
      const aspect = Math.max(long, short) / Math.max(1, Math.min(long, short));
      const share = area / (w * h);
      const skew = Math.max(...[0, 1, 2, 3].map(k => Math.abs(90 - angle(quad[(k + 3) % 4], quad[k], quad[(k + 1) % 4]))));
      const rovne = skew <= p.maxSkew && Math.max(sides[0], sides[2]) / Math.max(1, Math.min(sides[0], sides[2])) <= p.maxSideRatio &&
        Math.max(sides[1], sides[3]) / Math.max(1, Math.min(sides[1], sides[3])) <= p.maxSideRatio;
      const ok = rovne && fill >= p.minFill && share <= p.maxArea && aspect >= p.minAspect && aspect <= p.maxAspect;
      // Uvnitř je méně potisku než v pozadí: karta odešla a „vidí" se jen
      // díra po ní (pozadí se učilo s kartou na stole) → pozadí naučit znovu.
      const hole = ok && energy(gray, quad) < energy(bg, quad) * 0.6;
      return {
        ok: ok && !hole, hole, fill, aspect, share, skew,
        corners: quad.map(([x, y]) => [x / w, y / h]),
      };
    }
    // Součet gradientů uvnitř obdélníku čtyřúhelníku (potisk karty).
    function energy(g, quad) {
      const xs = quad.map(q => q[0]), ys = quad.map(q => q[1]);
      const x0 = Math.max(1, Math.floor(Math.min(...xs))), x1 = Math.min(w - 2, Math.ceil(Math.max(...xs)));
      const y0 = Math.max(1, Math.floor(Math.min(...ys))), y1 = Math.min(h - 2, Math.ceil(Math.max(...ys)));
      let sum = 0;
      for (let y = y0; y <= y1; y += 2) {
        for (let x = x0; x <= x1; x += 2) {
          const i = y * w + x;
          sum += Math.abs(g[i + 1] - g[i - 1]) + Math.abs(g[i + w] - g[i - w]);
        }
      }
      return sum;
    }
    return {find, setBackground, hasBackground: () => !!bg, params: Object.freeze(Object.assign({}, p))};
  }

  // ── Geometrie ───────────────────────────────────────────────────────────────
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  // Úhel ve vrcholu b mezi body a a c, ve stupních.
  function angle(a, b, c) {
    const v1 = [a[0] - b[0], a[1] - b[1]], v2 = [c[0] - b[0], c[1] - b[1]];
    const cos = (v1[0] * v2[0] + v1[1] * v2[1]) / Math.max(1e-9, Math.hypot(...v1) * Math.hypot(...v2));
    return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
  }
  function hull(points) {   // monotone chain, proti směru hodinových ručiček (y dolů = po směru)
    const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (pts.length < 3) return pts;
    const lower = [], upper = [];
    for (const pt of pts) {
      while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], pt) <= 0) lower.pop();
      lower.push(pt);
    }
    for (let i = pts.length - 1; i >= 0; i--) {
      const pt = pts[i];
      while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], pt) <= 0) upper.pop();
      upper.push(pt);
    }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }
  // Čtyřúhelník z obalu: nejdelší úhlopříčka a nejvzdálenější bod na každé straně.
  function quadOf(h) {
    if (h.length < 4) return null;
    let a = 0, c = 0, best = -1;
    for (let i = 0; i < h.length; i++) {
      for (let j = i + 1; j < h.length; j++) {
        const d = dist(h[i], h[j]);
        if (d > best) { best = d; a = i; c = j; }
      }
    }
    let b = -1, d = -1, bMax = 0, dMin = 0;
    for (let i = 0; i < h.length; i++) {
      const s = cross(h[a], h[c], h[i]);
      if (s > bMax) { bMax = s; b = i; }
      if (s < dMin) { dMin = s; d = i; }
    }
    if (b < 0 || d < 0) return null;
    return order([h[a], h[b], h[c], h[d]]);
  }
  // Pořadí: levý horní, pravý horní, pravý dolní, levý dolní (po směru hodin).
  function order(q) {
    const cx = q.reduce((s, p) => s + p[0], 0) / 4, cy = q.reduce((s, p) => s + p[1], 0) / 4;
    const sorted = q.slice().sort((p1, p2) => Math.atan2(p1[1] - cy, p1[0] - cx) - Math.atan2(p2[1] - cy, p2[0] - cx));
    let start = 0, min = Infinity;
    sorted.forEach((pt, i) => { if (pt[0] + pt[1] < min) { min = pt[0] + pt[1]; start = i; } });
    return sorted.slice(start).concat(sorted.slice(0, start));
  }
  function polyArea(q) {
    let s = 0;
    for (let i = 0; i < q.length; i++) { const j = (i + 1) % q.length; s += q[i][0] * q[j][1] - q[j][0] * q[i][1]; }
    return Math.abs(s) / 2;
  }

  const api = {create, hull, quadOf, order, polyArea, DEFAULTS};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvQuad = api;
})(typeof window !== 'undefined' ? window : globalThis);
