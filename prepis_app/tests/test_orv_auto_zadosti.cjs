// Žádosti auto-sken ORV: stráž nad modulem evidence (static/js/orv_auto_zadosti.js).
// Karta, která po skenu zůstane na stole (i posunutá nebo s rukou v záběru),
// se do další žádosti sama nenaskenuje. Další se vezme až po prázdném stole
// nebo s jiným QR.
const {test} = require('node:test');
const assert = require('node:assert/strict');

const core = require('../static/js/orv_auto_core.js');
const {straz} = require('../static/js/orv_auto_zadosti.js');

const STEP = 125;
const QR_A = 'UBZ482615', QR_B = 'UBE037263';
const sig = v => new Array(144).fill(v);
const DESK = sig(60);
const card = (s, extra) => Object.assign({motion: 2, sharp: 300, edges: 0.09, sig: s, qr: null}, extra);
const moving = () => ({motion: 30, sharp: 20, edges: 0.05, sig: sig(80), qr: null});
const empty = () => ({motion: 2, sharp: 15, edges: 0.005, sig: DESK, qr: null});
const rep = (n, f) => Array.from({length: n}, f);

// Stejné zapojení jako orv_auto_zadosti.js: stráž rozhodne o každém výstřelu,
// potlačený výstřel se commitne bez odeslání, odeslaný sken nastaví stráž.
function run(frames) {
  const c = core.create();
  const s = straz(core.DEFAULTS.edgeMin);
  const sent = [], swallowed = [];
  let t = 0, id = 0;
  for (const f of frames) {
    const out = c.step(Object.assign({t}, f));
    s.tick(Object.assign({}, out, {edges: f.edges}));
    if (out.fire) {
      const qr = out.reason === 'qr' ? out.qr : null;
      if (s.smiFotit(out.reason, qr)) { sent.push({t, reason: out.reason, qr}); s.poSkenu(qr); }
      else swallowed.push({t, reason: out.reason});
      c.commit(++id);
    }
    t += STEP;
  }
  return {sent, swallowed, straz: s};
}

test('the core alone re-fires a nudged card; the guard swallows it', () => {
  const frames = [...rep(12, empty), ...rep(3, moving), ...rep(14, () => card(sig(100))),
    // Card nudged / arm in view: a new still scene, never an empty desk.
    ...rep(3, moving), ...rep(14, () => card(sig(130)))];
  const bare = core.create();
  let fires = 0, t = 0, id = 0;
  for (const f of frames) {
    if (bare.step(Object.assign({t}, f)).fire) { fires++; bare.commit(++id); }
    t += STEP;
  }
  assert.equal(fires, 2, 'without the guard the same card would be scanned twice');
  const r = run(frames);
  assert.equal(r.sent.length, 1);
  assert.equal(r.swallowed.length, 1);
});

test('after an empty desk the next card is scanned again', () => {
  const r = run([...rep(12, empty), ...rep(3, moving), ...rep(14, () => card(sig(100))),
    ...rep(3, moving), ...rep(8, empty), ...rep(3, moving), ...rep(14, () => card(sig(140)))]);
  assert.deepEqual(r.sent.map(x => x.reason), ['klid', 'klid']);
});

test('a different QR is scanned at once, the same QR never twice', () => {
  const r = run([...rep(12, empty), ...rep(3, moving), ...rep(6, () => card(sig(100), {qr: QR_A})),
    ...rep(3, moving), ...rep(6, () => card(sig(130), {qr: QR_A})),
    ...rep(3, moving), ...rep(14, () => card(sig(160), {qr: QR_B}))]);
  assert.deepEqual(r.sent.map(x => x.qr), [QR_A, QR_B]);
});

test('guard rules', () => {
  const s = straz(0.045);
  assert.equal(s.smiFotit('klid', null), true);
  s.poSkenu(null);
  assert.equal(s.smiFotit('klid', null), false);
  assert.equal(s.smiFotit('qr', QR_A), true, 'a QR card after a non-QR scan');
  assert.equal(s.tick({rearmed: 'nova-scena', edges: 0.09}), false, 'a new printed scene is not an empty desk');
  assert.equal(s.tick({rearmed: 'jiny-qr', edges: 0.09}), false);
  assert.equal(s.tick({rearmed: 'nova-scena', edges: 0.01}), true, 'a new still scene without print = empty desk');
  assert.equal(s.smiFotit('klid', null), true);
  s.poSkenu(QR_A);
  assert.equal(s.smiFotit('qr', QR_A), false);
  assert.equal(s.smiFotit('qr', QR_B), true);
  assert.equal(s.smiFotit('klid', null), false);
  assert.equal(s.tick({rearmed: 'prazdno', edges: 0.01}), true);
  assert.deepEqual(s.stav(), {cekame: false, posledniQr: null});
});

test('after a page reload the last QR card is not scanned again', () => {
  const s = straz(0.045);
  s.obnov(QR_A);
  assert.equal(s.smiFotit('qr', QR_A), false);
  assert.equal(s.smiFotit('qr', QR_B), true);
  s.obnov(null);
  assert.deepEqual(s.stav(), {cekame: true, posledniQr: QR_A});
});
