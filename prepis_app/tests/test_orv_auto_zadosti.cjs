// Žádosti auto-sken ORV: stráž nad modulem evidence (static/js/orv_auto_zadosti.js).
// Karta, která po skenu zůstane na stole (i posunutá nebo s rukou v záběru),
// se do další žádosti sama nenaskenuje. Další se vezme až po prázdném stole
// nebo s jiným QR.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const core = require('../static/js/orv_auto_core.js');
const {straz, PARAMETRY_STOLU} = require('../static/js/orv_auto_zadosti.js');

const STEP = 125;
const QR_A = 'UBZ482615', QR_B = 'UBE037263';
const sig = v => new Array(144).fill(v);
const DESK = sig(60);
const card = (s, extra) => Object.assign({motion: 2, sharp: 300, edges: 0.09, sig: s, qr: null}, extra);
const moving = () => ({motion: 30, sharp: 20, edges: 0.05, sig: sig(80), qr: null});
const empty = () => ({motion: 2, sharp: 15, edges: 0.005, sig: DESK, qr: null});
const rep = (n, f) => Array.from({length: n}, f);
const {edgeMin, rearmMs} = core.DEFAULTS;

// Stejné zapojení jako orv_auto_zadosti.js: stráž rozhodne o každém výstřelu,
// potlačený výstřel se commitne bez odeslání, odeslaný sken nastaví stráž.
function run(frames) {
  const c = core.create(PARAMETRY_STOLU);
  const s = straz(edgeMin, rearmMs);
  const sent = [], swallowed = [];
  let t = 0, id = 0;
  for (const f of frames) {
    const out = c.step(Object.assign({t}, f));
    s.tick({...out, t, edges: f.edges});
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
  const bare = core.create(PARAMETRY_STOLU);
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
  const s = straz(edgeMin, rearmMs);
  assert.equal(s.smiFotit('klid', null), true);
  s.poSkenu(null);
  assert.equal(s.smiFotit('klid', null), false);
  assert.equal(s.smiFotit('qr', QR_A), true, 'a QR card after a non-QR scan');
  const desk = {stable: true, quad: false, edges: 0.01};
  assert.equal(s.tick({...desk, t: 0, edges: 0.09, rearmed: 'prazdno'}), false, 'an obscured card can lose its outline');
  assert.equal(s.tick({...desk, t: 125, quad: true}), false);
  assert.equal(s.tick({...desk, t: 250}), false, 'one empty frame is not enough');
  assert.equal(s.tick({...desk, t: 250 + rearmMs}), true, 'the desk stayed clear without a new core rearm event');
  assert.equal(s.smiFotit('klid', null), true);
  s.poSkenu(QR_A);
  assert.equal(s.smiFotit('qr', QR_A), false);
  assert.equal(s.smiFotit('qr', QR_B), true);
  assert.equal(s.smiFotit('klid', null), false);
  assert.equal(s.tick({...desk, t: 1000}), false);
  assert.equal(s.tick({...desk, t: 1000 + rearmMs}), true);
  assert.deepEqual(s.stav(), {cekame: false, posledniQr: null});
});

test('after a page reload the last QR card is not scanned again', () => {
  const s = straz(edgeMin, rearmMs);
  s.obnov(QR_A);
  assert.equal(s.smiFotit('qr', QR_A), false);
  assert.equal(s.smiFotit('qr', QR_B), true);
  s.obnov(null);
  assert.deepEqual(s.stav(), {cekame: true, posledniQr: QR_A});
});

test('the desk driver keeps one stream and only sends scans when the scan step is active', async () => {
  const stream = {getTracks: () => [{stop: () => assert.fail('camera stopped')}]};
  const video = {readyState: 4, videoWidth: 160, videoHeight: 90, offsetParent: {}, srcObject: stream};
  const timers = [], scans = [], logs = [], outlines = [];
  let now = 0, scanStep = false, cardVisible = true, dialogOpen = false;
  const window = {
    performance: {now: () => now},
    enterSkenuje: () => scanStep,
    kameraLog: (...log) => logs.push(log),
    OrvQr: {create: () => ({prepare() {}, kind: () => 'mock', decode: async () => cardVisible ? QR_A : null})},
    OrvNahled: {create: () => ({quad: corners => outlines.push(corners), foto() {}})},
  };
  const document = {
    getElementById: id => id === 'camera-video' ? video : null,
    querySelector: () => dialogOpen,
    querySelectorAll: () => [],
    createElement: () => {
      const canvas = {width: 0, height: 0};
      canvas.getContext = () => ({drawImage() {}, getImageData: () => ({
        data: new Uint8ClampedArray(canvas.width * canvas.height * 4).map((_, i) => {
          const x = ((i >> 2) % canvas.width) / canvas.width;
          const y = Math.floor((i >> 2) / canvas.width) / canvas.height;
          if (!cardVisible || x < 0.2 || x >= 0.8 || y < 0.18 || y >= 0.82) return 70;
          return x > 0.28 && x < 0.72 && y > 0.28 && y < 0.72 && Math.floor(y * 50) % 2 ? 110 : 225;
        }),
      })});
      return canvas;
    },
  };
  const context = vm.createContext({
    window, document, cameraStream: stream, _scanInFlight: false,
    navigator: {mediaDevices: {getUserMedia: () => assert.fail('camera reopened')}},
    localStorage: {getItem: () => null, setItem() {}},
    setInterval() {},
    setTimeout(fn, delay) { if (delay === STEP) timers.push(fn); },
    quickScanOrv: async options => {
      scans.push(options);
      window.orvAuto.poOdeslani(QR_A, true);
      return true;
    },
  });
  for (const file of ['orv_auto_core', 'orv_quad', 'orv_auto', 'orv_auto_zadosti']) {
    vm.runInContext(fs.readFileSync(require.resolve('../static/js/' + file + '.js'), 'utf8'), context);
  }
  async function frames(n) {
    for (let i = 0; i < n; i++) { now += STEP; timers.shift()(); await Promise.resolve(); }
  }

  await frames(16);
  assert.equal(scans.length, 0);
  scanStep = dialogOpen = true;
  await frames(16);
  assert.equal(scans.length, 0);
  dialogOpen = false;
  await frames(16);
  assert.equal(scans.length, 1);
  assert.ok(outlines.some(corners => corners?.length === 4));
  assert.match(scans[0].zachyt, /^qr .*quad=1$/);
  scanStep = false;
  await frames(16);
  scanStep = true; // novaZadost reuses the same video and stream
  await frames(16);
  assert.equal(scans.length, 1);
  cardVisible = false;
  await frames(12);
  cardVisible = true;
  await frames(16);
  assert.equal(scans.length, 2, 'an empty desk lets the QR be scanned again');
  assert.equal(video.srcObject, stream);
  assert.equal(logs.filter(([event]) => event === 'auto_foto').length, 2);
  assert.ok(logs.some(([event]) => event === 'auto_prazdno'));
});
