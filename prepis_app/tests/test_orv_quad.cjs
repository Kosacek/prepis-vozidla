// Rohy karty (static/js/orv_quad.js): obrys sedí na skutečné rohy i u natočené
// karty, a když to karta není (ruka přes ni, nic na stole), nekreslí se nic.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const Q = require('../static/js/orv_quad.js');

const W = 256, H = 192;
const GUIDE = {x: 0.08, y: 0.06, w: 0.84, h: 0.88};
const desk = () => new Uint8Array(W * H).fill(96);

// Karta 136 × 86 px (poměr ORV) se středem cx, cy, natočená o deg; potisk uvnitř.
function cardCorners(cx, cy, deg, cw = 136, ch = 86) {
  const r = deg * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  return [[-cw / 2, -ch / 2], [cw / 2, -ch / 2], [cw / 2, ch / 2], [-cw / 2, ch / 2]]
    .map(([x, y]) => [cx + x * c - y * s, cy + x * s + y * c]);
}
function inside(pt, poly) {
  let ins = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
function draw(frame, poly, print = true) {
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!inside([x + 0.5, y + 0.5], poly)) continue;
      const nearEdge = [[-4, 0], [4, 0], [0, -4], [0, 4]]
        .some(([dx, dy]) => !inside([x + 0.5 + dx, y + 0.5 + dy], poly));
      frame[y * W + x] = print && !nearEdge && y % 9 < 2 && x % 23 > 6 ? 60 : 225;
    }
  }
  return frame;
}
for (const deg of [0, 12, -22, 35]) {
  test(`corners hug a card tilted ${deg}°`, () => {
    const corners = cardCorners(128, 96, deg);
    const found = Q.create().find(draw(desk(), corners), W, H, GUIDE);
    assert.ok(found, 'card outline found on the first frame');
    const error = Math.min(...corners.map((_, shift) => Math.max(...found.map(([x, y], i) => {
      const [cx, cy] = corners[(i + shift) % 4];
      return Math.hypot(x * W - cx, y * H - cy);
    }))));
    assert.ok(error <= 4, `error ${error}`);
  });
}

test('removing a card leaves no outline', () => {
  const q = Q.create();
  assert.ok(q.find(draw(desk(), cardCorners(128, 96, 0)), W, H, GUIDE));
  assert.equal(q.find(desk(), W, H, GUIDE), null);
});

test('a hand over the card is not a card', () => {
  const frame = draw(desk(), cardCorners(110, 100, 8));
  draw(frame, [[150, 60], [250, 20], [256, 70], [170, 110]], false);   // forearm reaching in
  assert.equal(Q.create().find(frame, W, H, GUIDE), null);
});

test('a square or a whole-frame lighting change is not a card', () => {
  const q = Q.create();
  assert.equal(q.find(draw(desk(), cardCorners(128, 96, 10, 90, 90)), W, H, GUIDE), null);
  const bright = new Uint8Array(W * H).fill(200);
  assert.equal(q.find(bright, W, H, GUIDE), null);
});
