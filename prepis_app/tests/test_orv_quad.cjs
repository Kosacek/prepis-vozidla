// Rohy karty (static/js/orv_quad.js): obrys sedí na skutečné rohy i u natočené
// karty, a když to karta není (ruka přes ni, nic na stole), nekreslí se nic.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const Q = require('../static/js/orv_quad.js');

const W = 256, H = 192;
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
      frame[y * W + x] = print && y % 9 < 2 && x % 23 > 6 ? 60 : 225;  // řádky potisku
    }
  }
  return frame;
}
function maxCornerError(found, expected) {
  return Math.max(...found.map((pt, i) => Math.hypot(pt[0] * W - expected[i][0], pt[1] * H - expected[i][1])));
}
function detector() {
  const q = Q.create();
  q.setBackground(desk(), W, H);
  return q;
}

for (const deg of [0, 12, -22, 35]) {
  test(`corners hug a card tilted ${deg}°`, () => {
    const corners = cardCorners(128, 96, deg);
    const r = detector().find(draw(desk(), corners), W, H);
    assert.ok(r && r.ok, JSON.stringify(r && {fill: r.fill, aspect: r.aspect}));
    const expected = Q.order(corners);
    assert.ok(maxCornerError(r.corners, expected) <= 3, `error ${maxCornerError(r.corners, expected)}`);
  });
}

test('no background, nothing on the desk or a blank frame → no outline', () => {
  const q = Q.create();
  assert.equal(q.find(draw(desk(), cardCorners(128, 96, 0)), W, H), null, 'without a learned desk');
  assert.equal(detector().find(desk(), W, H), null, 'empty desk');
});

test('a hand over the card is not a card', () => {
  const frame = draw(desk(), cardCorners(110, 100, 8));
  draw(frame, [[150, 60], [250, 20], [256, 70], [170, 110]], false);   // forearm reaching in
  const r = detector().find(frame, W, H);
  assert.ok(!r || !r.ok);
});

test('a square or a whole-frame lighting change is not a card', () => {
  const square = detector().find(draw(desk(), cardCorners(128, 96, 10, 90, 90)), W, H);
  assert.ok(!square || !square.ok);
  const bright = new Uint8Array(W * H).fill(200);
  const r = detector().find(bright, W, H);
  assert.ok(!r || !r.ok);
});

test('the hole left by a card that was in the background is reported, not drawn', () => {
  const q = Q.create();
  q.setBackground(draw(desk(), cardCorners(128, 96, 5)), W, H);   // learned with the card on the desk
  const r = q.find(desk(), W, H);
  assert.ok(r && r.hole && !r.ok);
});

test('corners come in screen order: top-left, top-right, bottom-right, bottom-left', () => {
  const o = Q.order([[200, 150], [50, 40], [210, 30], [40, 160]]);
  assert.deepEqual(o, [[50, 40], [210, 30], [200, 150], [40, 160]]);
});
