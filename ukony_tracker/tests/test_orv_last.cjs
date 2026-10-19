const {test} = require('node:test');
const assert = require('node:assert/strict');

function fresh(store = {}) {
  globalThis.localStorage = {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }};
  delete require.cache[require.resolve('../static/js/orv_last.js')];
  return {L: require('../static/js/orv_last.js'), store};
}
const result = {stav: 'doplneno', ukon: {id: 3}};

test('save keeps results and thumbnails, load returns them', async () => {
  const {L} = fresh();
  await L.save([{thumb: 'data:a', result, upraveno: true}, {thumb: 'data:b', result: null}]);
  const got = L.load();
  assert.equal(got.items.length, 1);
  assert.deepEqual(got.items[0], {thumb: 'data:a', result, upraveno: true});
});

test('old, empty or corrupted records are ignored', () => {
  const {L, store} = fresh();
  store[L.KEY] = JSON.stringify({at: 0, items: [{result}]});
  assert.equal(L.load(15 * 24 * 3600 * 1000), null);
  store[L.KEY] = '{broken';
  assert.equal(L.load(), null);
  store[L.KEY] = JSON.stringify({at: Date.now(), items: [{result: {}}]});
  assert.equal(L.load(), null);
});

test('full storage falls back to results without thumbnails', async () => {
  const store = {};
  globalThis.localStorage = {getItem: k => store[k] ?? null, setItem: (k, v) => {
    if (v.includes('data:a')) throw Error('quota'); store[k] = v; }};
  delete require.cache[require.resolve('../static/js/orv_last.js')];
  const L = require('../static/js/orv_last.js');
  await L.save([{thumb: 'data:a', result}]);
  assert.equal(L.load().items[0].thumb, '');
});

test('label says Dnes for today, date otherwise', () => {
  const {L} = fresh();
  const now = new Date(2026, 9, 19, 15, 0);
  assert.equal(L.label(new Date(2026, 9, 19, 9, 5).getTime(), now), 'Dnes 9:05');
  assert.equal(L.label(new Date(2026, 9, 17, 14, 30).getTime(), now), '17. 10. 14:30');
});
