// Hands-free ORV capture: the pure decision core, the QR helper and the driver.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const core = require('../static/js/orv_auto_core.js');
const qrApi = require('../static/js/orv_qr.js');

const STEP = 125; // 8 fps
const QR_A = 'UBZ482615', QR_B = 'UBE037263';
const sig = v => new Array(144).fill(v);
const CARD_A = sig(100), CARD_B = sig(150), DESK = sig(60), TEXTURED_DESK = sig(200);
// One analysed frame of a card held still in the guide.
const still = (s, extra) => Object.assign({motion: 2, sharp: 300, edges: 0.09, sig: s || CARD_A, qr: null}, extra);
const moving = extra => Object.assign({motion: 30, sharp: 20, edges: 0.05, sig: sig(80), qr: null}, extra);
const empty = extra => Object.assign({motion: 2, sharp: 15, edges: 0.005, sig: DESK, qr: null}, extra);

// Feeds frames; every fire is committed as photo 1, 2, … unless `onFire` says otherwise.
function run(auto, frames, t0, onFire) {
  let t = t0 || 0, id = 0;
  const fires = [];
  for (const f of frames) {
    const out = auto.step(Object.assign({t}, f));
    if (out.fire) {
      fires.push({t, reason: out.reason, qr: out.qr});
      if (onFire) onFire(auto, ++id); else auto.commit(++id);
    }
    t += STEP;
  }
  return {fires, t};
}
const times = (n, f) => Array.from({length: n}, () => f);

test('metrics tell a sharp printed card from a flat blur', () => {
  const w = 40, h = 20;
  const flat = new Uint8Array(w * h).fill(128);
  const print = new Uint8Array(w * h).map((_, i) => ((i % w) >> 1) % 2 ? 230 : 20);
  assert.equal(core.sharpness(flat, w, h), 0);
  assert.ok(core.sharpness(print, w, h) > 1000);
  assert.equal(core.edges(flat, w, h), 0);
  assert.ok(core.edges(print, w, h) > 0.4);
  assert.equal(core.motion(flat, flat), 0);
  assert.equal(core.motion(null, flat), null);
  assert.ok(core.motion(flat, print) > 50);
  assert.equal(core.sigDiff(core.signature(flat, w, h), core.signature(flat, w, h)), 0);
  const rgba = new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]);
  assert.deepEqual(Array.from(core.gray(rgba, 2, 1)), [255, 0]);
});

test('a still desk never fires: something has to move in first', () => {
  const auto = core.create();
  assert.deepEqual(run(auto, times(60, still(TEXTURED_DESK))).fires, []);
});

test('raising the phone over a textured desk fires nothing', () => {
  const auto = core.create();
  assert.deepEqual(run(auto, [...times(3, moving()), ...times(40, still(TEXTURED_DESK))]).fires, []);
});

test('a card already held up when the camera opens waits for the shutter or a QR', () => {
  const auto = core.create();
  assert.deepEqual(run(auto, [...times(3, moving()), ...times(40, still())]).fires, []);
  const withQr = core.create();
  assert.equal(run(withQr, [...times(3, moving()), ...times(10, still(CARD_A, {qr: QR_A}))]).fires.length, 1);
});

test('a hand passing over a textured desk fires nothing (review 2026-11-22)', () => {
  const auto = core.create();
  const frames = [...times(10, still(TEXTURED_DESK)), ...times(3, moving()), ...times(40, still(TEXTURED_DESK))];
  assert.deepEqual(run(auto, frames).fires, []);
});

test('a card held still fires once after the hold time, never again while it stays', () => {
  const auto = core.create();
  const {fires} = run(auto, [...times(4, still(DESK)), ...times(3, moving()), ...times(40, still())]);
  assert.equal(fires.length, 1);
  assert.equal(fires[0].reason, 'klid');
  const hold = fires[0].t - 7 * STEP;
  assert.ok(hold >= core.DEFAULTS.holdMs && hold < core.DEFAULTS.holdMs + 2 * STEP, String(hold));
});

test('blur, a bare hand or shaking never fire', () => {
  for (const frame of [still(CARD_A, {sharp: 40}), still(CARD_A, {edges: 0.02}), still(CARD_A, {motion: 9})]) {
    const auto = core.create();
    assert.deepEqual(run(auto, [...times(3, moving()), ...times(40, frame)]).fires, [], JSON.stringify(frame));
  }
});

test('the next card fires only after the first one leaves', () => {
  const auto = core.create();
  const frames = [...times(4, empty()), ...times(3, moving()), ...times(16, still()),   // card A → photo
    ...times(4, moving()), ...times(4, empty()),                                          // taken away
    ...times(3, moving()), ...times(16, still(CARD_B))];                                  // card B → photo
  assert.deepEqual(run(auto, frames).fires.map(f => f.reason), ['klid', 'klid']);
});

test('the idle background coming back re-arms but never fires by itself', () => {
  const auto = core.create();
  const frames = [...times(4, still(TEXTURED_DESK)), ...times(3, moving()), ...times(16, still()),
    ...times(3, moving()), ...times(30, still(TEXTURED_DESK))];
  assert.equal(run(auto, frames).fires.length, 1);
});

test('a direct swap to a card without QR fires (review 2026-11-22)', () => {
  const auto = core.create();
  const frames = [...times(4, empty()), ...times(3, moving()), ...times(16, still()),
    ...times(3, moving()), ...times(30, still(CARD_B))];
  assert.deepEqual(run(auto, frames).fires.map(f => f.reason), ['klid', 'klid']);
});

test('a new QR fires at once; the same QR never twice in a row', () => {
  const auto = core.create();
  const qrA = {qr: QR_A};
  const frames = [...times(4, still(CARD_A, qrA)), ...times(20, still(CARD_A, qrA)),
    ...times(4, empty()), ...times(20, still(CARD_A, qrA))];           // same card back
  const {fires} = run(auto, frames);
  assert.equal(fires.length, 1);
  assert.equal(fires[0].reason, 'qr');
  assert.equal(fires[0].qr, QR_A);
  assert.ok(fires[0].t <= core.DEFAULTS.qrHoldMs + 2 * STEP);
});

test('swapping straight to a card with another QR fires after the cooldown', () => {
  const auto = core.create();
  const frames = [...times(4, still(CARD_A, {qr: QR_A})), ...times(20, still(CARD_B, {qr: QR_B}))];
  const {fires} = run(auto, frames);
  assert.deepEqual(fires.map(f => f.qr), [QR_A, QR_B]);
  assert.ok(fires[1].t - fires[0].t >= core.DEFAULTS.cooldownMs);
});

test('a QR that flickers still counts while the card stays put', () => {
  const auto = core.create();
  const flicker = [still(CARD_A, {qr: QR_A}), still(), still(), still()];
  const {fires} = run(auto, [...flicker, ...flicker]);
  assert.equal(fires.length, 1);
  assert.equal(fires[0].qr, QR_A);
});

test('a QR read before the card moved never rides along with the next one (review 2026-11-22)', () => {
  const auto = core.create();
  // A read lands, the card is swapped at once, the new card has no QR.
  const frames = [...times(2, moving()), still(CARD_A, {qr: QR_A}), ...times(2, moving()), ...times(30, still(CARD_B))];
  const {fires} = run(auto, [...times(4, empty()), ...frames]);
  assert.equal(fires.length, 1);
  assert.equal(fires[0].qr, null);
  // A late read stamped with a frame from before the movement is ignored too.
  const late = core.create();
  const t = run(late, [...times(4, empty()), ...times(3, moving())]).t;
  const out = late.step(still(CARD_B, {t, qr: QR_A, qrT: t - 3 * STEP}));
  assert.equal(out.qr, null);
});

test('a failed photo is released and the card fires again', () => {
  const auto = core.create();
  let failed = false;
  const {fires} = run(auto, [...times(4, still(CARD_A, {qr: QR_A})), ...times(20, still(CARD_A, {qr: QR_A}))], 0,
    (a, id) => { if (!failed) { failed = true; a.release(); } else a.commit(id); });
  assert.equal(fires.length, 2);
  assert.ok(fires[1].t - fires[0].t >= core.DEFAULTS.cooldownMs);
});

test('a manual shot locks the card, so no automatic duplicate follows', () => {
  const auto = core.create();
  run(auto, [...times(4, empty()), ...times(3, moving()), ...times(4, still())]);
  auto.manual(7, null);
  assert.deepEqual(run(auto, times(30, still()), 2000).fires, []);
});

test('removing the latest photo lets the card still in view be taken again', () => {
  for (const extra of [{qr: QR_A}, {}]) {
    const auto = core.create();
    const first = run(auto, [...times(4, empty()), ...times(3, moving()), ...times(20, still(CARD_A, extra))]);
    assert.equal(first.fires.length, 1);
    auto.forget(99);                       // another photo: nothing changes
    assert.deepEqual(run(auto, times(20, still(CARD_A, extra)), first.t).fires, []);
    auto.forget(1);                        // the photo of this card
    const again = run(auto, times(20, still(CARD_A, extra)), first.t + 20 * STEP);
    assert.equal(again.fires.length, 1, JSON.stringify(extra));
  }
});

test('only an exact ORV number counts as a QR', () => {
  for (const bad of ['ubz482615', 'UBZ4826151', 'UB0482615', 'UBZ 482615', ' UBZ482615', 'UBZ482615 ',
    'UBZ482615\n', '', null, 42, {}]) {
    assert.equal(core.cleanQr(bad), null, JSON.stringify(bad));
    assert.equal(qrApi.clean(bad), null, JSON.stringify(bad));
  }
  assert.equal(core.cleanQr(QR_A), QR_A);
  const auto = core.create();
  assert.deepEqual(run(auto, times(10, still(CARD_A, {qr: 'https://example.com'}))).fires, []);
});

function qrEnv(results) {
  const drawn = [];
  const ctx = {drawImage: (...a) => drawn.push(a.slice(1, 5).map(Math.round)),
    getImageData: () => ({data: [], width: 1, height: 1})};
  const document = {createElement: () => ({getContext: () => ctx})};
  let call = 0;
  function BarcodeDetector() {}
  BarcodeDetector.getSupportedFormats = async () => ['qr_code', 'ean_13'];
  BarcodeDetector.prototype.detect = async () => (results[call++] || []).map(rawValue => ({rawValue}));
  const window = {BarcodeDetector};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_qr.js'), 'utf8'),
    {window, document, setTimeout});
  return {reader: window.OrvQr.create({}), drawn};
}

test('the QR helper reads only inside the guide, top-right first', async () => {
  const {reader, drawn} = qrEnv([['not an orv'], [QR_A]]);
  const crop = {x: 0, y: 0, w: 1000, h: 1000};
  assert.equal(await reader.decode({}, crop), undefined); // not prepared yet
  assert.equal(await reader.prepare(), 'native');
  assert.equal(await reader.decode({}, crop), null);
  assert.equal(await reader.decode({}, crop), QR_A);
  assert.deepEqual(drawn[0], [500, 60, 420, 528]);        // top-right of the guide
  assert.deepEqual(drawn[1], [80, 60, 840, 880]);         // the whole guide, nothing outside it
});

test('two different ORV codes in view answer nothing', async () => {
  const {reader} = qrEnv([[QR_A, QR_B], [QR_A, QR_A, 'junk']]);
  await reader.prepare();
  assert.equal(await reader.decode({}, {x: 0, y: 0, w: 100, h: 100}), null);
  assert.equal(await reader.decode({}, {x: 0, y: 0, w: 100, h: 100}), QR_A);
});

test('the photo itself is read twice and both reads must agree', async () => {
  let env = qrEnv([[QR_A], []]);
  await env.reader.prepare();
  assert.equal(await env.reader.verify({}, 1800, 1013), QR_A);
  env = qrEnv([[QR_A], [QR_B]]);
  await env.reader.prepare();
  assert.equal(await env.reader.verify({}, 1800, 1013), null);
});

test('the capture summary always matches the server log pattern', () => {
  const auto = require('../static/js/orv_auto.js');
  const ZACHYT = /^(qr|klid|rucne)( [a-z]=[0-9]{1,5}(\.[0-9]{1,3})?){0,4}$/;
  for (const info of [{motion: 1.234, sharp: 312.6, edges: 0.0812}, {motion: null}, {},
    {motion: 1e9, sharp: 1e9, edges: 7}, null]) {
    for (const reason of ['qr', 'klid', 'rucne']) {
      const text = auto.zachyt(reason, info);
      assert.match(text, ZACHYT);
      assert.ok(text.length <= 60);
    }
  }
});

test('the driver feeds frames, fires through onFire and stops cleanly', async () => {
  // A fake video whose analysed copy is a sharp, still, printed card.
  const pixels = new Uint8ClampedArray(160 * 90 * 4).map((_, i) => ((i >> 2) % 160 >> 1) % 2 ? 230 : 20);
  const desk = new Uint8ClampedArray(160 * 90 * 4).fill(90);
  let frames = 0;
  const ctx = {drawImage() {}, getImageData: () => ({data: ++frames <= 4 ? desk : pixels})};
  const document = {createElement: () => ({width: 0, height: 0, getContext: () => ctx})};
  let now = 0;
  const timers = [];
  const window = {performance: {now: () => now}, console: {info() {}, debug() {}}};
  const context = {window, document, setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout() {}, Promise};
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_auto_core.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_auto.js'), 'utf8'), context);
  const fires = [];
  const video = {readyState: 4, videoWidth: 1920, videoHeight: 1080};
  const driver = window.OrvAuto.create({video, crop: () => ({x: 0, y: 0, w: 1920, h: 1080}),
    onFire: info => { fires.push(info); driver.commit(fires.length); }, canFire: () => true,
    params: {enterMotion: -1}});
  driver.start();
  for (let i = 0; i < 24 && timers.length; i++) { now += STEP; timers.shift()(); }
  driver.stop();
  assert.equal(fires.length, 1);
  assert.equal(fires[0].reason, 'klid');
  assert.match(fires[0].zachyt, /^klid m=0\.0 s=\d+ e=[01]\.\d{3}$/);
  if (timers.length) timers.shift()();
  assert.equal(timers.length, 0); // a stopped driver schedules nothing more
});
