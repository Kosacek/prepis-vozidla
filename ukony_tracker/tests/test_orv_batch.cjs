const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../static/js/orv_helpers.js');
const R = require('../static/js/orv_report.js');
const L = require('../static/js/orv_last.js');

class Element {
  constructor() {
    this.children = []; this.handlers = {}; this.dataset = {}; this.hidden = false; this.nodes = {};
    this.classList = new Set(); this.style = {};
    this.classList.remove = this.classList.delete.bind(this.classList);
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  setAttribute() {}
  remove() {}
  querySelector(name) { return this.nodes[name] || (this.nodes[name] = new Element()); }
}
function environment(stored = null, storageWorks = true) {
  const ids = new Map(), handlers = {}, windowHandlers = {}, requests = [], renders = [], saves = [], prompts = [];
  let add, reloads = 0, maxActive = 0, inFlight = 0, stops = 0, revoked = 0;
  let lastActions = null, lastPhotos = null, confirmClose = false;
  const el = name => {
    if (!ids.has(name)) ids.set(name, new Element());
    return ids.get(name);
  };
  const root = {querySelector: id => el(id.slice(5)), querySelectorAll: () => [], addEventListener: (name, fn) => { handlers[name] = fn; }, removeEventListener: name => { delete handlers[name]; }};
  const modal = el('ukon-modal');
  modal.classList.add('is-open');
  const document = {getElementById: id => id === 'orv-sken' ? root : el(id),
    createElement: () => new Element(), body: new Element(),
    addEventListener: (name, fn) => { handlers[name] = fn; },
    removeEventListener: name => { delete handlers[name]; },
    dispatchEvent(event) {
      handlers[event.type]?.(event);
      return !event.defaultPrevented;
    }};
  const window = {
    OrvLast: {...L, save(photos) {
      saves.push(photos.map(p => ({...p.result, upraveno: !!p.upraveno})));
      if (!storageWorks) return false;
      stored = {at: 1, items: photos.map(p => ({result: p.result, draft: L.draftOf(p)}))};
      return true;
    },
      load: () => stored, label: () => 'Dnes 9:05'},
    OrvHelpers: H, Thinking: () => ({start() {}, stop() {}}),
    OrvReport: {...R,
      render(_, photos, actions) { renders.push(photos.map(p => p.result)); lastActions = actions; lastPhotos = photos; },
      updateCreateCount() {}},
    OrvCamera: (_, addPhoto) => {
      add = addPhoto;
      return {start() {}, stop() { stops++; }, destroy() { stops++; }};
    },
    addEventListener: (name, fn) => { windowHandlers[name] = fn; },
    removeEventListener: (name, fn) => { if (windowHandlers[name] === fn) delete windowHandlers[name]; },
    location: {href: 'https://example.test/ukony', search: '', reload: () => reloads++},
    confirm: message => { prompts.push(message); return confirmClose; }
  };
  const context = vm.createContext({
    document, window, URLSearchParams, URL: class extends URL {
      static createObjectURL() { return 'blob:local'; }
      static revokeObjectURL() { revoked++; }
    },
    CustomEvent: class {
      constructor(type) { this.type = type; }
      preventDefault() { this.defaultPrevented = true; }
    },
    FormData: class {append() {}}, AbortController, setTimeout, clearTimeout,
    fetch: (url, options) => new Promise(resolve => {
      inFlight++; maxActive = Math.max(maxActive, inFlight);
      requests.push(Object.assign(result => {
        inFlight--; resolve({ok: true, json: async () => result});
      }, {url, options}));
    })
  });
  for (const filename of ['ukon_modal.js', 'orv_sken.js']) {
    vm.runInContext(fs.readFileSync(require.resolve('../static/js/' + filename), 'utf8'), context);
  }
  handlers['ukon:scan-shown']();
  function close(source) {
    const event = {target: source === 'scrim' ? modal : {closest: sel => sel === '[data-modal-close]'},
      key: source === 'Esc' ? 'Escape' : null, preventDefault() {}};
    if (source === 'Esc') handlers.keydown(event);
    else modal.handlers.click(event);
  }
  return {el, handlers, windowHandlers, requests, renders, saves, prompts, close, stored: () => stored,
    acceptClose: () => { confirmClose = true; }, isOpen: () => modal.classList.has('is-open'),
    add: () => add({size: 100}),
    actions: () => lastActions, photos: () => lastPhotos,
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
  // The retry action lives on the report card now; the action calls run([photo]).
  const photos = e.photos();
  const retried = e.actions().onRetry(photos[0]);
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

const changed = {stav: 'zmena_ke_kontrole', ukon: {id: 1711}, lze_zapsat: true,
  navrh_token: 'original-proposal-token', rz: '5AB1234', orv_cislo: 'UBP590636',
  zmeny: {orv: {pred: 'UBF670979', po: 'UBP590636'}}};

for (const source of ['×', 'scrim', 'Esc']) {
  test(source + ' checks unsaved drafts and pending decisions, cancel stays', async () => {
    const e = environment({at: 1, items: [{result: changed}, {result: {stav: 'bez_firmy'}}]});
    e.el('last').handlers.click();
    Object.assign(e.photos()[1], {firmaOverride: '14', cenaOverride: '800'});
    e.actions().onDraft();
    e.close(source);
    assert.deepEqual(e.prompts, ['Zavřít? 2 auta čekají na rozhodnutí.']);
    assert.equal(e.isOpen(), true);
    assert.equal(e.photos()[1].cenaOverride, '800');
    assert.equal(e.saves.length, 0);
    e.acceptClose();
    e.close(source);
    assert.equal(e.isOpen(), false);

    const reopened = environment(e.stored());
    reopened.el('last').handlers.click();
    assert.equal(reopened.photos()[1].firmaOverride, '14');
    assert.equal(reopened.photos()[1].cenaOverride, '800');
    const write = reopened.actions().onWrite(reopened.photos()[0]);
    assert.equal(reopened.requests[0].url, '/ukony/orv-sken/zapsat');
    assert.deepEqual(JSON.parse(reopened.requests[0].options.body),
      {ukon_id: 1711, token: changed.navrh_token});
    reopened.requests[0]({...success, ukon: {id: 1711}});
    await write;
    assert.equal(reopened.renders.at(-1)[0].stav, 'doplneno');
  });
}

test('an untouched new-car card remains pending and closing does not ask', () => {
  const e = environment({at: 1, items: [{result: {stav: 'bez_firmy', navrh_firma_id: 14}}]});
  e.el('last').handlers.click();
  e.photos()[0].firmaOverride = '14'; // Preselected by the report.
  e.close('×');
  assert.deepEqual(e.prompts, []);
  assert.equal(e.isOpen(), false);
});

function assertUnloadPrompt(e) {
  const event = {preventDefault() { this.defaultPrevented = true; }};
  e.windowHandlers.beforeunload(event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.returnValue, true);
}

test('beforeunload guards a pending proposal and is removed once it is skipped', () => {
  const e = environment({at: 1, items: [{result: changed}]});
  assert.equal(e.windowHandlers.beforeunload, undefined);
  e.el('last').handlers.click();
  assertUnloadPrompt(e);
  e.actions().onSkip(e.photos()[0]);
  assert.equal(e.windowHandlers.beforeunload, undefined);
});

test('beforeunload guards an unsaved edit and is removed when the dialog closes', () => {
  const e = environment({at: 1, items: [{result: {stav: 'bez_firmy'}}]});
  e.el('last').handlers.click();
  assert.equal(e.windowHandlers.beforeunload, undefined);
  e.photos()[0].poznamka = 'Rozpracováno';
  e.actions().onDraft();
  assertUnloadPrompt(e);
  e.acceptClose();
  e.close('×');
  assert.equal(e.isOpen(), false);
  assert.equal(e.windowHandlers.beforeunload, undefined);
  assert.equal(e.stored().items[0].draft.poznamka, 'Rozpracováno');
});

test('an untouched jiz_v_evidence card from an old report still needs a decision', () => {
  const e = environment({at: 1, items: [{result: {stav: 'jiz_v_evidence', ukon: {id: 10}}}]});
  e.el('last').handlers.click();
  assertUnloadPrompt(e);
  e.close('Esc');
  assert.deepEqual(e.prompts, ['Zavřít? 1 auto čeká na rozhodnutí.']);
  assert.equal(e.isOpen(), true);
  assertUnloadPrompt(e);
});

test('confirming close dismisses the dialog even if saving the report fails', () => {
  const e = environment({at: 1, items: [{result: changed}]}, false);
  e.el('last').handlers.click();
  e.acceptClose();
  e.close('×');
  assert.deepEqual(e.prompts, ['Zavřít? 1 auto čeká na rozhodnutí.']);
  assert.equal(e.saves.length, 1);
  assert.equal(e.isOpen(), false);
  assert.equal(e.windowHandlers.beforeunload, undefined);
});

test('Hotovo finishes a batch with written, unchanged, skipped, and pending cards', async () => {
  const template = fs.readFileSync(require.resolve('../templates/_orv_sken.html'), 'utf8');
  assert.match(template, /<button[^>]*data-modal-close[^>]*>Hotovo<\/button>/);
  const e = environment();
  for (let i = 0; i < 4; i++) e.add();
  const done = e.el('process').handlers.click();
  e.requests[0](success);
  e.requests[1]({stav: 'uz_zapsano', ukon: {id: 1710}});
  e.requests[2](changed);
  await tick();
  e.requests[3]({stav: 'bez_firmy'});
  await done;
  assert.equal(e.el('done').hidden, false);
  e.actions().onSkip(e.photos()[2]);
  assert.deepEqual(Array.from(e.photos(), photo => photo.result.stav),
    ['doplneno', 'uz_zapsano', 'preskoceno', 'bez_firmy']);
  e.close('Hotovo');
  assert.equal(e.isOpen(), false);
  assert.deepEqual(e.prompts, []);
  assert.equal(e.stats().reloads, 1);
  assert.equal(e.stored().items[3].result.stav, 'bez_firmy');
});
