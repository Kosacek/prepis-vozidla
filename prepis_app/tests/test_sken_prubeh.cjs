// Průběh skenu (static/js/sken_prubeh.js): rychlý start, zpomalující konec,
// nikdy necouvá, nikdy 100 % dřív, než je hotovo, a čas podle skutečných běhů.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const P = require('../static/js/sken_prubeh.js');

function clock() {
  let t = 0;
  const now = () => t;
  now.go = ms => { t += ms; return t; };
  return now;
}
const sample = (p, now, ms, step = 50) => {
  const out = [];
  for (let k = 0; k < ms; k += step) out.push(p.hodnota(now.go(step)));
  return out;
};

test('fast start, slow end, never backwards, never 100 % before the last milestone', () => {
  const now = clock();
  const p = P.create({}, now);
  const values = [p.hodnota(now())];
  values.push(...sample(p, now, 180));
  p.hotovo('foto');
  values.push(...sample(p, now, 500));
  p.uploadPodil(0.5);
  values.push(...sample(p, now, 100));
  p.hotovo('upload');
  values.push(...sample(p, now, 12000));          // the model takes ages
  for (let i = 1; i < values.length; i++) assert.ok(values[i] >= values[i - 1] - 1e-9, `backwards at ${i}`);
  const last = values[values.length - 1];
  assert.ok(last < 0.80, `ocr stage must stay below its ceiling, got ${last}`);
  assert.ok(last > 0.70, 'but keep moving towards it');
  // Early part moves faster than the tail of the long stage.
  const early = values[10] - values[0], late = values[values.length - 1] - values[values.length - 11];
  assert.ok(early > late * 5, `early ${early} late ${late}`);
  p.hotovo('ocr'); p.hotovo('pole');
  assert.ok(p.hodnota(now.go(10)) < 1);
  p.hotovo('registr');
  assert.equal(p.hodnota(now.go(10)), 1);
  assert.ok(p.hotovy());
});

test('a milestone that arrives early continues from the current value — no jump', () => {
  const now = clock();
  const p = P.create({}, now);
  now.go(20);
  const before = p.hodnota(now());
  p.hotovo('foto');
  const after = p.hodnota(now());
  assert.ok(Math.abs(after - before) < 0.01, `${before} → ${after}`);
});

test('skipping a milestone (no registry call) still records it and moves on', () => {
  const now = clock();
  const p = P.create({}, now);
  now.go(100); p.hotovo('upload');
  now.go(3000); p.hotovo('registr');
  assert.equal(p.hodnota(now()), 1);
  assert.deepEqual(Object.keys(p.casy()), ['foto', 'upload', 'ocr', 'pole', 'registr']);
});

test('the rolling median sets the pace', () => {
  const run = hist => {
    const now = clock();
    const p = P.create(hist, now);
    p.hotovo('upload', 0);
    return p.hodnota(now.go(2000));
  };
  const slowHist = {ocr: [9000, 9500, 10000]}, fastHist = {ocr: [1500, 1600, 1700]};
  assert.ok(run(fastHist) > run(slowHist) + 0.1);
  assert.equal(P.median([3, 1, 2]), 2);
  assert.equal(P.median([4, 1, 3, 2]), 2.5);
  assert.equal(P.median(['x', -1]), null);
});

test('failure freezes the bar and history keeps the last 15 per stage', () => {
  const now = clock();
  const p = P.create({ocr: Array.from({length: 15}, (_, i) => 1000 + i)}, now);
  now.go(300); p.hotovo('upload');
  now.go(4000);
  p.selhalo();
  const frozen = p.hodnota(now.go(5000));
  assert.equal(p.hodnota(now.go(5000)), frozen);
  assert.ok(p.chybny() && !p.hotovy());
  const ok = P.create({ocr: Array.from({length: 15}, (_, i) => 1000 + i)}, clock());
  ok.hotovo('registr', 2222);
  const h = ok.novaHistorie();
  assert.equal(h.ocr.length, 15);
  assert.equal(h.ocr[14], 0);   // all stages done at the same instant in this test
  assert.equal(h.registr.length, 1);
});
