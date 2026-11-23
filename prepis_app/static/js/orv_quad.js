// ORV outline on a small grayscale frame. Adapted from the Žádosti quad
// detector: reuse the hull and card geometry checks with live contours so the
// first frame can already contain a card. No DOM, timers or learned background.
(function (root) {
  'use strict';
  const EDGE = 32;

  function create() {
    let mask = new Uint8Array(0), stack = new Int32Array(0);

    function find(gray, w, h, guide) {
      if (mask.length !== w * h) {
        mask = new Uint8Array(w * h);
        stack = new Int32Array(w * h);
      }
      mask.fill(0);
      for (let y = 1; y < h - 1; y++) {
        for (let x = 1; x < w - 1; x++) {
          const i = y * w + x;
          if (Math.abs(gray[i + 1] - gray[i - 1]) + Math.abs(gray[i + w] - gray[i - w]) >= EDGE) {
            // Bridge one-pixel breaks in the outline at this analysis resolution.
            for (let dy = -1; dy <= 1; dy++) mask.fill(1, i + dy * w - 1, i + dy * w + 2);
          }
        }
      }

      const left = new Int32Array(h), right = new Int32Array(h);
      let best = null, bestArea = 0;
      for (let i = 0; i < mask.length; i++) {
        if (!mask[i]) continue;
        left.fill(w);
        right.fill(-1);
        let top = 0, clipped = false;
        push(i);
        while (top) {
          const j = stack[--top], x = j % w, y = Math.floor(j / w);
          left[y] = Math.min(left[y], x);
          right[y] = Math.max(right[y], x);
          if (x === 0 || y === 0 || x === w - 1 || y === h - 1) clipped = true;
          if (x > 0 && mask[j - 1]) push(j - 1);
          if (x < w - 1 && mask[j + 1]) push(j + 1);
          if (y > 0 && mask[j - w]) push(j - w);
          if (y < h - 1 && mask[j + w]) push(j + w);
        }
        function push(j) {
          mask[j] = 0;
          stack[top++] = j;
        }
        if (clipped) continue;

        const points = [];
        for (let y = 0; y < h; y++) {
          if (right[y] >= 0) points.push([left[y], y], [right[y], y]);
        }
        if (points.length < h * 0.3) continue;
        const outline = hull(points);
        const quad = quadOf(outline);
        if (!quad) continue;
        const area = polyArea(quad);
        if (area <= bestArea || area < w * h * 0.08 || area > w * h * 0.92 ||
            area < polyArea(outline) * 0.88) continue;
        const sides = quad.map((pt, k) => dist(pt, quad[(k + 1) % 4]));
        const a = (sides[0] + sides[2]) / 2, b = (sides[1] + sides[3]) / 2;
        const aspect = Math.max(a, b) / Math.min(a, b);
        if (aspect < 1.2 || aspect > 2.2 || sides[0] / sides[2] > 1.5 || sides[2] / sides[0] > 1.5 ||
            sides[1] / sides[3] > 1.5 || sides[3] / sides[1] > 1.5 ||
            quad.some((pt, k) => Math.abs(90 - angle(quad[(k + 3) % 4], pt, quad[(k + 1) % 4])) > 25)) continue;
        const cx = quad.reduce((sum, pt) => sum + pt[0], 0) / (4 * w);
        const cy = quad.reduce((sum, pt) => sum + pt[1], 0) / (4 * h);
        if (cx < guide.x || cx > guide.x + guide.w || cy < guide.y || cy > guide.y + guide.h) continue;
        if (!quad.every((pt, k) => supported(gray, w, h, pt, quad[(k + 1) % 4], sides[k]))) continue;

        bestArea = area;
        best = quad.map(([x, y]) => [x / w, y / h]);
      }
      return best;
    }
    return {find};
  }

  // Each side must have an edge for most of its length. A hull alone also
  // fits open shapes, wood grain and isolated bits of printing.
  function supported(gray, w, h, a, b, length) {
    const nx = (b[1] - a[1]) / length, ny = (a[0] - b[0]) / length;
    const pixel = (x, y) => gray[Math.round(y) * w + Math.round(x)];
    let hits = 0;
    for (let k = 1; k <= 9; k++) {
      const x = a[0] + (b[0] - a[0]) * k / 10, y = a[1] + (b[1] - a[1]) * k / 10;
      const x0 = x - 5 * nx, y0 = y - 5 * ny, x1 = x + nx, y1 = y + ny;
      if (Math.min(x0, x1) < 0 || Math.min(y0, y1) < 0 ||
          Math.max(x0, x1) > w - 1 || Math.max(y0, y1) > h - 1) continue;
      if (Math.abs(pixel(x0, y0) - pixel(x1, y1)) >= EDGE) hits++;
    }
    return hits >= 6;
  }
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

  const api = {create};
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OrvQuad = api;
})(typeof window !== 'undefined' ? window : globalThis);
