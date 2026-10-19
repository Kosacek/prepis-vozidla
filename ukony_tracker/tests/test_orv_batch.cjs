const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../static/js/orv_helpers.js');

class Element {
  constructor() { this.children = []; this.handlers = {}; this.dataset = {}; this.hidden = false; this.nodes = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  setAttribute() {}
  remove() {}
  querySelector(name) { return this.nodes[name] || (this.nodes[name] = new Element()); }
}
function environment(stored = null) {
  const ids = new Map(), handlers = {}, requests = [], renders = [], saves = [];
  let add, reloads = 0, maxActive = 0, inFlight = 0, stops = 0, revoked = 0;
  const el = name => {
    if (!ids.has(name)) ids.set(name, new Element());
    return ids.get(name);
  };
  const root = {querySelector: id => el(id.slice(5)), querySelectorAll: () => []};
  const document = {getElementById: () => root, createElement: () => new Element(),
    addEventListener: (name, fn) => { handlers[name] = fn; },
    removeEventListener: name => { delete handlers[name]; }};
  const window = {
    OrvLast: {save: photos => saves.push(photos.map(p => ({...p.result, upraveno: !!p.upraveno}))),
      load: () => stored, label: () => 'Dnes 9:05'},
    OrvHelpers: H, Thinking: () => ({start() {}, stop() {}}),
    OrvReport: {render(_, photos) { renders.push(photos.map(p => p.result)); }, selected() { return []; }, updateCreateCount() {}},
    OrvCamera: (_, addPhoto) => {
      add = addPhoto;
      return {start() {}, stop() { stops++; }, destroy() { stops++; }};
    },
    addEventListener() {}, location: {reload: () => reloads++},
    UkonModal: {close: () => handlers['ukon:modal-closing']({preventDefault() {}})}
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../static/js/orv_sken.js'), 'utf8'), {
    document, window, URL: {createObjectURL: () => 'blob:local', revokeObjectURL: () => revoked++},
    FormData: class {append() {}}, AbortController, setTimeout, clearTimeout,
    fetch: () => new Promise(resolve => {
      inFlight++; maxActive = Math.max(maxActive, inFlight);
      requests.push(result => { inFlight--; resolve({ok: true, json: async () => result}); });
    })
  });
  handlers['ukon:scan-shown']();
  return {el, handlers, requests, renders, saves, add: () => add({size: 100}),
    stats: () => ({reloads, maxActive, inFlight, stops, revoked})};
}
const tick = () => new Promise(setImmediate);
const success = {stav: 'doplneno', doplneno: ['rz', 'orv'], zprava: 'Doplněno',
  ukon: {id: 1, firma: 'BSAuto', datum: '2026-10-08'}};

test('one tap processes the batch with three requests maximum and live rows', async () => {
  const e = environment();
  for (let i = 0; i < 10; i++) e.add();
  const done = e.el('process').handlers.click();
  assert.equal(e.requests.length, 3);
  assert.equal(e.stats().stops, 1);
  for (let i = 0; i < 10; i++) {
    assert.ok(e.requests[i], 'next photo is scheduled as an earlier photo finishes');
    e.requests[i](success);
    await tick();
    assert.equal(e.el('results').children[i].dataset.state, 'ok');
  }
  await done;
  assert.equal(e.stats().maxActive, 3);
  assert.equal(e.el('summary').hidden, false);
  assert.equal(e.el('summary').hidden, false);
});

test('close stops queued photos, waits for active writes, then releases photos and refreshes', async () => {
  const e = environment();
  for (let i = 0; i < 10; i++) e.add();
  const done = e.el('process').handlers.click();
  let prevented = false;
  e.handlers['ukon:modal-closing']({preventDefault: () => { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(e.stats().reloads, 0);
  e.requests.slice().forEach(resolve => resolve(success));
  await done;
  assert.equal(e.requests.length, 3);
  assert.equal(e.stats().reloads, 1);
  assert.equal(e.stats().revoked, 10);
});

test('failed photo can be retried without reprocessing successful photos', async () => {
  const e = environment(); e.add(); e.add();
  const done = e.el('process').handlers.click();
  e.requests[0]({stav: 'chyba', zprava: 'Chyba', doplneno: []});
  e.requests[1](success);
  await done;
  const retry = e.el('results').children[0].children[1].children[2];
  assert.equal(retry.hidden, false);
  assert.equal(retry.disabled, false);
  const retried = retry.handlers.click();
  assert.equal(e.requests.length, 3);
  e.requests[2](success);
  await retried;
  const last = e.renders[e.renders.length - 1];
  assert.equal(last.length, 2);
  assert.ok(last.every(r => r.stav === 'doplneno'));
});

test('batch accepts at most thirty photos', () => {
  const e = environment();
  for (let i = 0; i < 31; i++) e.add();
  assert.equal(e.el('counter').textContent, '30 fotek');
  assert.equal(e.el('thumbnails').children.length, 30);
  assert.ok(e.el('note').textContent.includes('30'));
  e.handlers['ukon:modal-closing']({preventDefault() {}});
});

test('saving an edited úkon keeps the report and marks that car as edited', async () => {
  const e = environment();
  e.add();
  const done = e.el('process').handlers.click();
  e.requests[0](success);
  await done;
  assert.equal(e.saves.length, 1);
  e.handlers['ukon:saved']({detail: {id: '1'}});
  assert.equal(e.saves.length, 2);
  assert.equal(e.saves[1][0].upraveno, true);
  assert.equal(e.el('results').hidden, false);
  assert.equal(e.el('summary').hidden, false);
  assert.equal(e.stats().reloads, 0);
});

test('last scan button reopens the stored report without re-saving it', () => {
  const e = environment({at: 1, items: [{thumb: 'data:x', result: success, upraveno: true}]});
  assert.equal(e.el('last').hidden, false);
  assert.equal(e.el('last-time').textContent, 'Dnes 9:05');
  e.el('last').handlers.click();
  assert.deepEqual(e.renders.at(-1), [success]);
  assert.equal(e.el('summary').hidden, false);
  assert.equal(e.el('capture').hidden, true);
  assert.equal(e.el('last').hidden, true);
  assert.equal(e.saves.length, 0);
});
