/* Tests for the Techničák report (2.7.2): pure helpers + a fake-DOM smoke
   test of the compact result cards. The cards follow the /ukony rows and every
   car carries its own firm/type — there is no shared "apply to all" bar.
   2.7.2: the photo sits top-right (body before preview in the DOM), a new car's
   price moved from the RZ line down to the note row, the verbose note
   placeholder is gone and the shared FirmaPick gets the firm colours. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// -- Minimal fake DOM (createElement, append, querySelector) ----------------
class Node {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase();
    this.children = [];
    this.parent = null;
    this.className = '';
    this.dataset = {};
    this.attributes = {};
    this.handlers = {};
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.type = '';
    this.id = '';
    this.src = '';
    this.alt = '';
    this._text = '';
  }
  get textContent() {
    return this.children.length ? this.children.map(c => c.textContent).join('') : this._text;
  }
  set textContent(value) {
    this.children = [];
    this._text = value == null ? '' : String(value);
  }
  append(...nodes) {
    nodes.forEach(node => {
      if (node == null) return;
      const list = Array.isArray(node) ? node : [node];
      list.forEach(child => {
        if (child == null) return;
        child.parent = this;
        this.children.push(child);
      });
    });
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null; }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this);
    this.parent = null;
  }
  querySelector(selector) { return descendants(this).find(n => matches(n, selector)) || null; }
  querySelectorAll(selector) { return descendants(this).filter(n => matches(n, selector)); }
}
function descendants(node) {
  const out = [];
  node.children.forEach(child => { out.push(child, ...descendants(child)); });
  return out;
}
function classes(node) { return String(node.className || '').split(/\s+/).filter(Boolean); }
function matchesSimple(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return classes(node).includes(selector.slice(1));
  return node.tagName === selector.toUpperCase();
}
// Simple selectors plus descendant chains (".orv-card-noterow .orv-card-price").
function matches(node, selector) {
  const parts = String(selector || '').trim().split(/\s+/);
  if (parts.length === 1) return matchesSimple(node, parts[0]);
  if (!matchesSimple(node, parts[parts.length - 1])) return false;
  let index = parts.length - 2;
  let current = node.parent;
  while (current && index >= 0) {
    if (matchesSimple(current, parts[index])) index--;
    current = current.parent;
  }
  return index < 0;
}
const fakeDocument = {createElement: tag => new Node(tag)};
globalThis.document = fakeDocument;

const R = require('../static/js/orv_report.js');

const photo = (id, stav, extra = {}) => ({id, result: {stav, ...extra}});
const kc = n => new Intl.NumberFormat('cs-CZ', {maximumFractionDigits: 0}).format(n) + ' Kč';
const plain = value => String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
const FIRMS = [{id: 14, nazev: 'JE & NE', zkratka: 'JN', color: '#123456'},
  {id: 15, nazev: 'BSAuto Brno', zkratka: 'BS', color: '#654321'}];
const DATA = {ceny: {14: {'PŘEVOD': 1300}, 15: {'NOVÉ': 950}}, firmy: FIRMS};

function optionNode(value, label, color) {
  const option = new Node('option');
  option.value = value;
  option.textContent = label;
  if (color) option.dataset.color = color; // the fragment's data-color
  return option;
}
// Mirrors the fragment's fixed nodes: summary, sections and the hidden bank of
// firm/type options the per-card <select>s copy from.
function mountRoot(data = DATA) {
  const root = new Node('section');
  ['summary', 'summary-title', 'counts', 'create-unmatched', 'review', 'written',
    'written-title', 'unassigned', 'issues', 'results'].forEach(id => {
    const node = new Node(id === 'counts' || id === 'results' ? 'div' : 'div');
    node.id = 'orv-' + id;
    root.append(node);
  });
  const firmaOptions = new Node('select');
  firmaOptions.id = 'orv-firma-options';
  firmaOptions.append(optionNode('', '— vyber firmu —'));
  FIRMS.forEach(f => firmaOptions.append(optionNode(String(f.id), f.nazev, f.color)));
  const typOptions = new Node('select');
  typOptions.id = 'orv-typ-options';
  typOptions.append(optionNode('', '— vyber typ —'));
  ['PŘEVOD', 'NOVÉ'].forEach(kod => typOptions.append(optionNode(kod, kod)));
  const dataNode = new Node('script');
  dataNode.id = 'orv-data';
  dataNode.textContent = data == null ? '{}' : (typeof data === 'string' ? data : JSON.stringify(data));
  root.append(firmaOptions, typOptions, dataNode);
  return root;
}
function render(photos, data = DATA) {
  const root = mountRoot(data);
  R.render(root, photos, {});
  return root;
}
const cards = root => root.querySelector('#orv-results').children;
const issues = root => root.querySelector('#orv-issues').children;
const unassigned = root => root.querySelector('#orv-unassigned').children;
const allText = node => node.textContent;

// -- Grouping / states ------------------------------------------------------
test('report puts cars to decide first and written cards after them', () => {
  const photos = [photo(1, 'uz_doplneno'), photo(2, 'necitelne'), photo(3, 'zalozeno'),
    photo(4, 'konflikt'), photo(5, 'doplneno'), photo(6, 'bez_firmy'), photo(7, 'chyba')];
  assert.deepEqual(R.group(photos).map(p => p.id), [6, 4, 7, 2, 3, 5, 1]);
  assert.deepEqual(R.reviewPhotos(photos).map(p => p.id), [6, 4, 7, 2]);
  assert.deepEqual(R.writtenPhotos(photos).map(p => p.id), [3, 5, 1]);
  assert.deepEqual(photos.map(p => p.id), [1, 2, 3, 4, 5, 6, 7]); // input untouched
});

test('duplicate cars stay in the review section, also as the new jiz_v_evidence state', () => {
  assert.equal(R.needsAction(photo(1, 'jiz_v_evidence')), true);
  assert.equal(R.assignable(photo(1, 'jiz_v_evidence')), true);
  assert.equal(R.assignable(photo(2, 'bez_firmy')), true);
  assert.equal(R.assignable(photo(3, 'zalozeno')), false);
  assert.equal(R.needsAction(photo(3, 'zalozeno')), false);
  assert.equal(R.isWritten(photo(3, 'zalozeno')), true);
  assert.equal(R.isWritten(photo(4, 'uz_doplneno')), true);
});

test('banner is green only when there is nothing left to decide', () => {
  assert.deepEqual(R.bannerState([photo(1, 'zalozeno'), photo(2, 'doplneno')]),
    {review: 0, text: 'Vše v pořádku', tone: 'ok'});
  assert.deepEqual(R.bannerState([photo(1, 'bez_firmy'), photo(2, 'necitelne')]),
    {review: 2, text: 'Zkontroluj 2 auta', tone: 'warn'});
  assert.deepEqual(R.bannerState([photo(1, 'jiz_v_evidence')]),
    {review: 1, text: 'Zkontroluj 1 auto', tone: 'warn'});
});

test('summary counts created, filled, unchanged, review and unreadable cars', () => {
  assert.deepEqual(R.totals(['zalozeno', 'doplneno', 'uz_doplneno', 'bez_firmy', 'jiz_v_evidence', 'necitelne']
    .map((state, id) => photo(id, state))),
    {zalozeno: 1, doplneno: 1, uz_doplneno: 1, review: 2, necitelne: 1});
});

test('summary chips show only non-zero counts, in a fixed order', () => {
  const photos = ['zalozeno', 'zalozeno', 'doplneno', 'necitelne', 'bez_firmy']
    .map((state, id) => photo(id, state));
  assert.deepEqual(R.summaryChips(photos).map(c => [c.key, c.n, c.text]), [
    ['zalozeno', 2, '✚ Založeno · 2'],
    ['doplneno', 1, '✎ Doplněno · 1'],
    ['review', 1, '⚠ Ke kontrole · 1'],
    ['necitelne', 1, '✗ Nečitelné · 1'],
  ]);
  // No zeros at all — the whole point of 2.7.1.
  assert.ok(R.summaryChips(photos).every(c => c.n > 0 && !c.text.includes('· 0')));
  assert.deepEqual(R.summaryChips([]), []);
});

test('Czech car and create-button plurals handle one, two to four and five plus', () => {
  assert.deepEqual([1, 2, 4, 5].map(R.czechCars), ['auto', 'auta', 'auta', 'aut']);
  assert.deepEqual([1, 2, 4, 5].map(R.czechJobs), ['úkon', 'úkony', 'úkony', 'úkonů']);
});

// -- Duplicate guard --------------------------------------------------------
test('the duplicate warning names the existing úkon, its firm, price and payment', () => {
  assert.equal(R.existingLine({id: 1537, datum: '2026-10-27', firma: 'JE & NE', firma_zkratka: 'JN',
    typ: 'PŘEVOD', celkem: 1300, stav_platby: 'zaplaceno', poznamka: 'ACC'}),
  '#1537 · 27. 10. 2026 · PŘEVOD · JN · Zaplaceno');
  // Older payload without firma_zkratka keeps the full firm name.
  assert.equal(R.existingLine({id: 7, firma: 'JE & NE'}), '#7 · JE & NE');
});

test('a duplicate is flagged by existujici, by vyzaduje_potvrzeni or by the new state', () => {
  assert.equal(R.needsConfirm({result: {stav: 'bez_firmy', existujici: [{id: 1}]}}), true);
  assert.equal(R.needsConfirm({result: {stav: 'bez_firmy', vyzaduje_potvrzeni: true}}), true);
  assert.equal(R.needsConfirm({result: {stav: 'jiz_v_evidence'}}), true);
  assert.equal(R.needsConfirm({result: {stav: 'bez_firmy', existujici: []}}), false);
  assert.equal(R.needsConfirm({result: {stav: 'bez_firmy'}}), false);
  assert.equal(R.needsConfirm({}), false);
  // Older/short payload: the one úkon it did send is still shown.
  assert.deepEqual(R.visibleExisting({stav: 'jiz_v_evidence', ukon: {id: 1537}}).map(v => v.id), [1537]);
});

test('candidate úkony for vice_shod/konflikt are capped at five', () => {
  const candidates = Array.from({length: 7}, (_, i) => ({id: i + 1, datum: '2026-10-27',
    firma: 'F', typ: 'NOVÉ', stav_platby: 'nezaplaceno'}));
  assert.deepEqual(R.kandidati({kandidati: candidates}).map(v => v.id), [1, 2, 3, 4, 5]);
  assert.deepEqual(R.kandidati({kandidati: [{id: null}, {id: 3}]}).map(v => v.id), [3]);
  assert.deepEqual(R.kandidati({}), []);
});

// -- Selection & payload (per car, no shared bar) --------------------------
test('every car is selected only when it has its own firm AND type', () => {
  const cars = [photo(1, 'bez_firmy'), photo(2, 'bez_firmy')];
  // Nothing chosen on the cards → nothing to create (no shared defaults).
  assert.deepEqual(R.selected(cars), []);
  cars[0].firmaOverride = '14';
  assert.deepEqual(R.selected(cars), []); // firma without typ is not enough
  cars[0].typOverride = 'PŘEVOD';
  cars[1].firmaOverride = '15';
  cars[1].typOverride = 'NOVÉ';
  assert.deepEqual(R.selected(cars).map(x => [x.photo.id, x.firma_id, x.typ_kod]),
    [[1, '14', 'PŘEVOD'], [2, '15', 'NOVÉ']]);
  // A third car with a different firm stays independent — no inheritance.
  cars[0].firmaOverride = '15';
  assert.deepEqual(R.selected(cars).map(x => x.firma_id), ['15', '15']);
});

test('a duplicate car is not counted until "Přesto založit nový úkon" is checked', () => {
  const car = photo(1, 'bez_firmy', {existujici: [{id: 1537}], vyzaduje_potvrzeni: true});
  car.firmaOverride = '14'; car.typOverride = 'PŘEVOD';
  assert.deepEqual(R.selected([car]), []);
  car.potvrdit = true;
  const chosen = R.selected([car]);
  assert.equal(chosen.length, 1);
  assert.equal(R.payload(car, chosen[0]).potvrdit_novy, true);
  // The same car coming back as jiz_v_evidence after submit is excluded again.
  car.result = {stav: 'jiz_v_evidence', existujici: [{id: 1537}]};
  car.potvrdit = false;
  assert.deepEqual(R.selected([car]), []);
});

test('create payload carries the read car, the firm, the note and the confirmation', () => {
  const car = {id: 1, poznamka: '  ACC  ', result: {
    stav: 'bez_firmy', rz: '1AKI647', vin: 'TMBER6NW0V3099310', orv_cislo: 'UBP585023',
    provozovatel: 'JE & NE', vin_zdroj: 'registr', existujici: [{id: 1537}]}};
  assert.deepEqual(R.payload(car, {firma_id: '14', typ_kod: 'NOVÉ'}), {
    rz: '1AKI647', vin: 'TMBER6NW0V3099310', orv_cislo: 'UBP585023', provozovatel: 'JE & NE',
    vin_zdroj: 'registr', firma_id: 14, typ_kod: 'NOVÉ', potvrdit_novy: false, poznamka: 'ACC'});
  // ≤120 chars; empty note is not sent at all (manual form stores NULL).
  car.poznamka = 'x'.repeat(140);
  assert.equal(R.payload(car, {firma_id: '14', typ_kod: 'NOVÉ'}).poznamka.length, 120);
  car.poznamka = '   ';
  assert.equal('poznamka' in R.payload(car, {firma_id: '14', typ_kod: 'NOVÉ'}), false);
  assert.equal(R.noteValue(null), '');
});

test('the create button counts only assignable, complete and confirmed cars', () => {
  const root = mountRoot();
  const button = root.querySelector('#orv-create-unmatched');
  const cars = [photo(1, 'bez_firmy', {rz: '1AA1111'}), photo(2, 'necitelne'),
    photo(3, 'bez_firmy', {existujici: [{id: 9}]})];
  assert.equal(R.updateCreateCount(root, cars), 0);
  assert.equal(button.textContent, 'Založit 0 úkonů');
  assert.equal(button.disabled, true);
  assert.equal(button.hidden, false);
  cars[0].firmaOverride = '14'; cars[0].typOverride = 'PŘEVOD';
  assert.equal(R.updateCreateCount(root, cars), 1);
  assert.equal(button.textContent, 'Založit 1 úkon');
  assert.equal(button.disabled, false);
  cars[2].firmaOverride = '15'; cars[2].typOverride = 'NOVÉ'; cars[2].potvrdit = true;
  assert.equal(R.updateCreateCount(root, cars), 2);
  assert.equal(button.textContent, 'Založit 2 úkony');
  // Nothing to create → the button disappears (the form only shows issues).
  assert.equal(R.updateCreateCount(root, [photo(9, 'necitelne')]), 0);
  assert.equal(button.hidden, true);
});

test('a car rejected as already in evidence keeps its card and drops the stale check', () => {
  const first = {id: 1, result: {stav: 'bez_firmy'}, potvrdit: true, firmaOverride: '14',
    typOverride: 'PŘEVOD', poznamka: 'ACC'};
  const second = {id: 2, result: {stav: 'bez_firmy'}, potvrdit: false};
  const blocked = R.applyCreateResults([{photo: first}, {photo: second}],
    [{stav: 'zalozeno', ukon: {id: 1600}}, {stav: 'jiz_v_evidence', existujici: [{id: 1537}],
      zprava: 'Toto auto už má úkon #1537.'}]);
  assert.deepEqual(blocked.map(p => p.id), [2]);
  assert.equal(first.result.ukon.id, 1600);
  assert.equal(first.firmaOverride, '14'); // typed inputs stay
  assert.equal(first.poznamka, 'ACC');
  assert.equal(second.potvrdit, false);
  assert.equal(R.needsAction(second), true);
});

// -- Prices & #orv-data JSON ----------------------------------------------
test('live price reads ceny by firm and type, and stays honest when missing', () => {
  const ceny = {'14': {'NOVÉ': 1300, 'PŘEVOD': null}, 15: {'NOVÉ': 950.5}};
  assert.equal(R.priceFor(ceny, '14', 'NOVÉ'), 1300);
  assert.equal(R.priceFor(ceny, 14, 'NOVÉ'), 1300);
  assert.equal(R.priceFor(ceny, '15', 'NOVÉ'), 950.5);
  assert.equal(R.priceFor(ceny, '14', 'PŘEVOD'), null);
  assert.equal(R.priceFor(ceny, '14', 'KOLA'), null);
  assert.equal(R.priceFor({}, '14', 'NOVÉ'), null);
  assert.equal(R.priceFor(ceny, '', 'NOVÉ'), null);
  assert.equal(R.priceLabel(ceny, {firma_id: '14', typ_kod: 'NOVÉ'}), 'Cena: ' + kc(1300));
  assert.equal(R.priceLabel(ceny, {firma_id: '14', typ_kod: 'PŘEVOD'}), 'Cena: —');
  assert.equal(R.priceLabel(ceny, {firma_id: '', typ_kod: ''}), 'Cena: —');
  assert.equal(R.kc(null), '—');
});

test('#orv-data carries prices and firm colours; a missing/broken block is empty', () => {
  const root = mountRoot();
  assert.deepEqual(R.cenyOf(root), DATA.ceny);
  assert.equal(R.firmsOf(root)['14'].color, '#123456');
  assert.equal(R.firmsOf(root)['15'].zkratka, 'BS');
  assert.deepEqual(R.cenyOf(mountRoot({ceny: {14: {'NOVÉ': 1300}}})), {14: {'NOVÉ': 1300}});
  assert.deepEqual(R.firmsOf(mountRoot({ceny: {}})), {});
  assert.deepEqual(R.cenyOf(mountRoot('{"ceny": null}')), {});
  assert.deepEqual(R.firmsOf(mountRoot('{broken')), {});
  assert.deepEqual(R.cenyOf(mountRoot(null)), {});
  // Defensive: an id-keyed firm object (older shape) still maps.
  const legacy = R.firmsMap({firmy: {14: {nazev: 'JE & NE', zkratka: 'JN', color: '#000'}}});
  assert.deepEqual(legacy, {14: {id: '14', nazev: 'JE & NE', zkratka: 'JN', color: '#000'}});
});

test('firm identity uses the colour map by firma_id and falls back for old payloads', () => {
  const firms = R.firmsOf(mountRoot());
  assert.deepEqual(R.firmOf({firma_id: 14, firma_zkratka: 'JN', firma: 'JE & NE'}, firms),
    {zkratka: 'JN', color: '#123456'});
  // firma_zkratka wins over the local map's name, colour still comes from the map
  assert.deepEqual(R.firmOf({firma_id: 15}, firms), {zkratka: 'BS', color: '#654321'});
  // Older payload: firma_id missing → match the firm by its zkratka/název.
  assert.deepEqual(R.firmOf({firma: 'JE & NE'}, firms), {zkratka: 'JN', color: '#123456'});
  // Nothing to match → muted dot, never a crash.
  assert.deepEqual(R.firmOf({firma: 'Neznámá'}, firms), {zkratka: 'Neznámá', color: 'var(--muted)'});
  assert.deepEqual(R.firmOf({}, firms), {zkratka: '—', color: 'var(--muted)'});
  assert.deepEqual(R.firmOf(null, null), {zkratka: '—', color: 'var(--muted)'});
});

// -- Read facts / changes ---------------------------------------------------
test('cards show everything the scan read, including what it did not read', () => {
  const facts = R.readFactsList({rz: '3BR9309', vin: 'TMBER6NW0V3099310', vin_zdroj: 'registr',
    orv_cislo: null});
  assert.deepEqual(facts.map(f => [f.label, f.value]),
    [['RZ', '3BR9309'], ['VIN', 'TMBER6NW0V3099310'], ['ORV', null]]);
  assert.deepEqual(facts.map(R.factText),
    ['RZ 3BR9309', 'VIN TMBER6NW0V3099310 · z registru', 'ORV nepřečteno']);
  assert.equal(R.factText(R.readFactsList({orv_cislo: 'UBP588302'})[2]), 'ORV UBP588302');
  assert.deepEqual(R.readFactsList({}).map(f => f.value), [null, null, null]);
});

test('a car seen before shows the earlier úkon, not as a match', () => {
  assert.equal(R.earlier({predchozi: {id: 883, datum: '2026-08-26', firma: 'JE & NE',
    firma_zkratka: 'JN', typ: 'PŘEVOD'}}), 'Dříve 26. 8. 2026 · JN · PŘEVOD');
  assert.equal(R.earlier({}), null);
  assert.equal(R.earlier({predchozi: {datum: 'ne-datum'}}), null);
});

// -- No bulk "apply to all" UI ---------------------------------------------
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
test('the shared "firma and typ for all cars" bar is gone from template and JS', () => {
  const template = read('templates/_orv_sken.html');
  const report = read('static/js/orv_report.js');
  const sken = read('static/js/orv_sken.js');
  for (const source of [template, report, sken]) {
    assert.equal(/orv-batch/.test(source), false);
    assert.equal(/Společná firma/.test(source), false);
    assert.equal(/batchDefaults/.test(source), false);
    assert.equal(/firmaOverride\s*\|\|.*defaults/.test(source), false);
  }
  assert.equal(/"firmy"\s*:/.test(template), true); // #orv-data carries firm colours
  assert.equal(/id="orv-data"/.test(template), true);
});

test('the duplicate card keeps the bold warning but drops the explanatory paragraph', () => {
  const report = read('static/js/orv_report.js');
  const template = read('templates/_orv_sken.html');
  assert.equal(/orv-duplicate-hint/.test(report), false);
  assert.equal(/Sken ho našel dřív/.test(report + template), false);
  assert.equal(/Tohle auto už v evidenci je/.test(report), true);
});

// -- DOM: the compact cards ------------------------------------------------
test('render shows only non-zero summary chips', () => {
  const root = render([photo(1, 'zalozeno'), photo(2, 'doplneno'), photo(3, 'bez_firmy')]);
  const chips = root.querySelector('#orv-counts').querySelectorAll('.orv-count-chip');
  assert.deepEqual(chips.map(c => c.textContent), ['✚ Založeno · 1', '✎ Doplněno · 1', '⚠ Ke kontrole · 1']);
  assert.equal(root.querySelector('#orv-counts').hidden, false);
  assert.ok(!chips.some(c => c.textContent.includes('· 0')));
  // Nothing counted → no chips at all.
  const empty = render([]);
  assert.equal(empty.querySelector('#orv-counts').children.length, 0);
  assert.equal(empty.querySelector('#orv-counts').hidden, true);
});

test('a created card shows status, bold RZ, tag, price, ORV, firm dot and small action', () => {
  const root = render([photo(1, 'zalozeno', {rz: '1AKI647', orv_cislo: 'UBP585023',
    vin: 'TMBER6NW0V3099310', vin_zdroj: 'registr',
    ukon: {id: 1600, firma: 'JE & NE', firma_id: 14, firma_zkratka: 'JN', typ: 'PŘEVOD',
      celkem: 1300, pojamka: null}})]);
  const [card] = cards(root);
  assert.equal(card.dataset.state, 'created');
  assert.ok(hasClass(card, 'orv-card'));
  // Text body first, photo second → the photo sits in the right column.
  assert.deepEqual(card.children.map(c => c.className), ['orv-card-body', 'orv-card-preview']);
  assert.equal(card.querySelector('.orv-status').textContent, 'Založeno');
  assert.equal(card.querySelector('.orv-rz').textContent, '1AKI647');
  assert.equal(card.querySelector('.orv-typ').textContent, 'PŘEVOD');
  // Written cards keep the price on the RZ line, like /ukony rows.
  assert.ok(card.querySelector('.orv-card-id .orv-card-price'));
  assert.equal(card.querySelector('.orv-card-id .orv-card-price').textContent.replace(/\s+/g, ' ').trim(),
    plain(kc(1300)));
  assert.equal(card.querySelector('.orv-card-noterow'), null); // no assign fields on written cards
  assert.match(card.querySelector('.orv-orv').textContent, /ORV UBP585023/);
  assert.equal(card.querySelector('.orv-firm-name').textContent, 'JN');
  assert.equal(card.querySelector('.firma-dot').getAttribute('style'), 'background:#123456;');
  assert.match(card.querySelector('.orv-meta').textContent, /VIN TMBER6NW0V3099310/);
  assert.equal(card.querySelector('.orv-duplicate'), null);
  const open = card.querySelector('.orv-open-written');
  assert.equal(open.textContent, 'Otevřít a upravit úkon');
  assert.equal(open.dataset.ukon, '1600');
});

test('a filled card lists only the fields that really changed, beze změny none', () => {
  const filled = render([photo(1, 'doplneno', {rz: '1AKI647', orv_cislo: 'UBP588302',
    ukon: {id: 1600, firma_zkratka: 'JN', firma_id: 14, typ: 'PŘEVOD', celkem: 1300},
    zmeny: {rz: {pred: '1AKI647', po: '1AKI647'}, orv: {pred: 'UBP585023', po: 'UBP588302'},
      vin: {pred: null, po: null}}})]);
  const changes = cards(filled)[0].querySelectorAll('.orv-change');
  assert.equal(changes.length, 1);
  assert.match(changes[0].textContent, /ORV/);
  assert.match(changes[0].textContent, /UBP585023/);
  assert.match(changes[0].textContent, /UBP588302/);
  const same = render([photo(1, 'uz_doplneno', {rz: '1AKI647', orv_cislo: 'UBP585023',
    ukon: {id: 1600, firma_zkratka: 'JN', firma_id: 14, typ: 'PŘEVOD', celkem: 1300},
    zmeny: {rz: {pred: '1AKI647', po: '1AKI647'}}})]);
  assert.equal(same.querySelector('#orv-results').children[0].querySelectorAll('.orv-change').length, 0);
  assert.equal(same.querySelector('#orv-results').children[0].querySelector('.orv-status').textContent,
    'Beze změny');
});

test('an assign card has its own firm/type selects, note and live price next to it', () => {
  const car = photo(1, 'bez_firmy', {rz: '1AKI647', orv_cislo: 'UBP585023', vin: 'TMBER6NW0V3099310',
    provozovatel: 'JE & NE', navrh_firma_id: 14});
  const root = render([car]);
  const [card] = unassigned(root);
  assert.equal(card.dataset.state, 'assign');
  // The photo is top-right, the text stays left-aligned.
  assert.deepEqual(card.children.map(c => c.className), ['orv-card-body', 'orv-card-preview']);
  assert.equal(card.querySelector('.orv-status').textContent, 'Nové auto');
  assert.equal(card.querySelector('.orv-rz').textContent, '1AKI647');
  assert.equal(card.querySelector('.orv-firm'), null); // selects replace the read firm line
  // The price is NOT at the RZ line any more (it read like part of the plate).
  assert.equal(card.querySelector('.orv-card-id .orv-card-price'), null);
  assert.equal(card.querySelector('.orv-card-id .orv-card-price-k'), null);
  const selects = card.querySelectorAll('select');
  assert.equal(selects.length, 2);
  assert.equal(selects[0].value, '14'); // navrh_firma_id only pre-selects
  assert.equal(selects[1].value, '');
  assert.equal(card.querySelectorAll('input').length, 1); // poznámka
  assert.equal(card.querySelector('.orv-meta').textContent.includes('Provozovatel: JE & NE'), true);
  // Row 2: Poznámka (left) + Cena (right) in one dedicated row.
  const noterow = card.querySelector('.orv-card-noterow');
  assert.ok(noterow, 'note row exists');
  const note = noterow.querySelector('.orv-card-poznamka');
  assert.ok(note, 'note input lives in the note row');
  assert.equal(note.placeholder, 'Poznámka');
  assert.equal(note.maxLength, 120);
  const priceEl = noterow.querySelector('.orv-card-price');
  assert.equal(priceEl.textContent.replace(/\s+/g, ' ').trim(), 'Cena —');
  assert.equal(noterow.querySelector('.orv-card-price-k').textContent, 'Cena');
  // Choosing the type fills the live price in the SAME node and the button count.
  car.typOverride = 'PŘEVOD';
  card.querySelectorAll('select')[1].value = 'PŘEVOD';
  R.refreshPrices(root, [car]);
  assert.equal(card.querySelector('.orv-card-noterow .orv-card-price'), priceEl);
  assert.equal(priceEl.textContent.replace(/\s+/g, ' ').trim(), plain('Cena ' + kc(1300)));
  assert.equal(card.querySelector('.orv-typ').textContent, 'PŘEVOD');
  assert.equal(root.querySelector('#orv-create-unmatched').textContent, 'Založit 1 úkon');
  // Price honest when the type has no price.
  car.firmaOverride = '15'; car.typOverride = 'PŘEVOD';
  R.refreshPrices(root, [car]);
  assert.equal(priceEl.textContent.replace(/\s+/g, ' ').trim(), 'Cena —');
});

test('the verbose "nepovinná, max. 120" note placeholder is gone', () => {
  const report = read('static/js/orv_report.js');
  assert.equal(/nepovinná, max\. 120/.test(report), false);
  const [card] = unassigned(render([photo(1, 'bez_firmy', {})]));
  assert.equal(card.querySelector('.orv-card-poznamka').placeholder, 'Poznámka');
});

test('every card kind keeps body before the preview (photo top-right)', () => {
  const root = render([
    photo(1, 'zalozeno', {ukon: {id: 1, firma_id: 14, firma_zkratka: 'JN', typ: 'PŘEVOD', celkem: 1300}}),
    photo(2, 'doplneno', {ukon: {id: 2, firma_id: 14, firma_zkratka: 'JN', typ: 'PŘEVOD', celkem: 1300}}),
    photo(3, 'uz_doplneno', {ukon: {id: 3, firma_id: 14, firma_zkratka: 'JN', typ: 'PŘEVOD', celkem: 1300}}),
    photo(4, 'bez_firmy', {rz: '1AA1111'}),
    photo(5, 'jiz_v_evidence', {existujici: [{id: 9}]}),
    photo(6, 'necitelne', {zprava: 'RZ ani ORV nejsou čitelné.'}),
    photo(7, 'chyba', {zprava: 'Spojení se přerušilo.'}),
  ]);
  const all = cards(root).concat(unassigned(root), issues(root));
  assert.equal(all.length, 7);
  all.forEach(card => {
    assert.equal(card.children.length, 2, card.dataset.state + ' card has body+preview');
    assert.equal(card.children[0].className, 'orv-card-body');
    assert.equal(card.children[1].className, 'orv-card-preview');
    assert.equal(card.children[1].tagName, 'BUTTON');
    assert.equal(card.children[1].type, 'button');
    assert.ok(card.children[1].dataset.preview != null); // click-to-zoom hook kept
    // The only thing after the text column is the photo — nothing overflows.
    assert.equal(card.querySelectorAll('img').length, 1);
  });
});

test('bank firm colours land on the card options so FirmaPick can draw the dots', () => {
  const root = render([photo(1, 'bez_firmy', {navrh_firma_id: 14})]);
  const select = unassigned(root)[0].querySelector('.orv-card-firma');
  assert.deepEqual(select.querySelectorAll('option').map(o => [o.value, o.dataset.color]),
    [['', undefined], ['14', '#123456'], ['15', '#654321']]);
  // The fragment's bank must carry the colour from firma_colors.
  const template = read('templates/_orv_sken.html');
  assert.ok(template.includes('data-color="{{ firma_colors.get(firma.zkratka, \'var(--muted)\') }}"'));
});

test('the shared FirmaPick wraps the firm select when loaded; native select otherwise', () => {
  const calls = [];
  globalThis.FirmaPick = {attach(select) {
    calls.push(select);
    select.dataset.picker = '1';
  }};
  try {
    const root = render([photo(1, 'bez_firmy', {navrh_firma_id: 14}), photo(2, 'bez_firmy', {})]);
    const selects = unassigned(root).map(card => card.querySelector('.orv-card-firma'));
    assert.equal(calls.length, 2);
    assert.deepEqual(calls, selects); // attached to the real card selects
    assert.ok(calls.every(select => select.dataset.picker === '1'));
    assert.ok(calls.every(select => select.querySelectorAll('option').length === 3));
    assert.equal(selects[0].value, '14');
    assert.equal(selects[1].value, '');
  } finally {
    delete globalThis.FirmaPick;
  }
  // Older page (no firma_pick.js): no crash, the native select keeps working.
  const plain = render([photo(3, 'bez_firmy', {navrh_firma_id: 14})]);
  const select = unassigned(plain)[0].querySelector('.orv-card-firma');
  assert.equal(select.value, '14');
  assert.equal('picker' in select.dataset, false);
});

test('FirmaPick errors never break card rendering', () => {
  globalThis.FirmaPick = {attach() { throw new Error('boom'); }};
  try {
    const root = render([photo(1, 'bez_firmy', {})]);
    assert.equal(unassigned(root).length, 1);
  } finally {
    delete globalThis.FirmaPick;
  }
});

test('CSS puts the photo in a fixed right column, 46 px on small phones', () => {
  const css = read('static/css/orv_report.css');
  assert.match(css, /\.orv-card \{display:grid; grid-template-columns:minmax\(0,1fr\) 58px/);
  assert.match(css, /\.orv-card-preview \{display:block; align-self:start; width:58px/);
  assert.match(css, /\.orv-card-noterow \{display:flex; align-items:flex-end; gap:8px/);
  assert.match(css, /\.orv-card-noterow \.orv-card-price \{[^}]*margin-left:auto/);
  assert.equal(/\.orv-card-field--wide/.test(css), false); // dead rule after the note row move
  const small = css.slice(css.indexOf('@media (max-width:560px)'),
    css.indexOf('@media (orientation:landscape)'));
  assert.match(small, /\.orv-card \{grid-template-columns:minmax\(0,1fr\) 46px/);
  assert.match(small, /\.orv-card-preview \{width:46px; height:46px;\}/);
  // 375 px: single-column fields, note row still one row with the price right.
  assert.match(small, /\.orv-card-fields \{grid-template-columns:minmax\(0,1fr\);\}/);
});

test('a duplicate card keeps the bold warning, existing úkon and confirm checkbox — no paragraph', () => {
  const car = photo(1, 'jiz_v_evidence', {rz: '1AKI647', orv_cislo: null,
    existujici: [{id: 1537, datum: '2026-10-27', firma: 'JE & NE', firma_zkratka: 'JN',
      typ: 'PŘEVOD', celkem: 1300, stav_platby: 'zaplaceno'}],
    ukon: {id: 1537, firma_zkratka: 'JN', firma_id: 14, typ: 'PŘEVOD',
      datum: '2026-10-27', stav_platby: 'zaplaceno'}});
  const root = render([car]);
  const [card] = unassigned(root);
  assert.equal(card.dataset.state, 'duplicate');
  const warning = card.querySelector('.orv-duplicate');
  assert.ok(warning);
  assert.match(warning.querySelector('.orv-duplicate-title').textContent, /Tohle auto už v evidenci je/);
  assert.equal(warning.querySelector('.orv-duplicate-hint'), null);
  assert.match(warning.querySelector('.orv-existing-line').textContent, /#1537/);
  assert.equal(warning.querySelector('.orv-open-existing').dataset.ukon, '1537');
  const checkbox = warning.querySelector('.orv-confirm-input');
  assert.equal(checkbox.type, 'checkbox');
  assert.equal(checkbox.checked, false);
  // Unread ORV is the red flag that caused it — and the RZ still reads.
  assert.ok(hasClass(card.querySelector('.orv-orv'), 'orv-orv--missing'));
  assert.match(card.querySelector('.orv-orv').textContent, /ORV nepřečteno/);
  assert.match(card.textContent, /Přesto založit nový úkon/);
});

test('an unreadable card offers a new photo, a transient error both retake and retry', () => {
  const unreadable = render([{id: 1, blob: {}, url: '', result: {stav: 'necitelne',
    zprava: 'RZ ani číslo ORV nejsou čitelné.'}}]);
  const [card] = issues(unreadable);
  assert.equal(card.dataset.state, 'unreadable');
  assert.equal(card.querySelector('.orv-retake-btn').textContent, 'Vyfotit znovu');
  assert.equal(card.querySelector('.orv-retry-btn'), null);
  assert.match(card.querySelector('.orv-message').textContent, /RZ ani číslo ORV/);
  const broken = render([{id: 2, blob: {}, url: '', result: {stav: 'chyba',
    zprava: 'Spojení se přerušilo. Zkuste to znovu.'}}]);
  const [error] = issues(broken);
  assert.equal(error.dataset.state, 'warn');
  assert.equal(error.querySelector('.orv-retake-btn').textContent, 'Vyfotit znovu');
  assert.equal(error.querySelector('.orv-retry-btn').textContent, 'Přečíst znovu');
});

test('konflikt shows the evidence-vs-photo line, vice_shod its candidate úkony', () => {
  const conflict = render([photo(1, 'konflikt', {rz: '1AKI647',
    konflikt: {pole: 'orv', evidence: 'UBP585023', foto: 'UBP588302'},
    ukon: {id: 1520, firma: 'JE & NE', firma_id: 14, firma_zkratka: 'JN', typ: 'PŘEVOD'},
    zprava: 'ORV je jiné. V evidenci: UBP585023 · Na fotce: UBP588302'})]);
  const [card] = issues(conflict);
  assert.match(card.querySelector('.orv-conflict').textContent, /V evidenci: UBP585023/);
  assert.match(card.querySelector('.orv-conflict').textContent, /Na fotce: UBP588302/);
  assert.equal(card.querySelector('.orv-message'), null); // the conflict block says it
  // The one matched úkon stays reachable (old card had an "Otevřít úkon" too).
  assert.equal(card.querySelector('.orv-open-issue').dataset.ukon, '1520');
  const vice = render([photo(2, 'vice_shod', {rz: '1AKI647', kandidati: [
    {id: 1, datum: '2026-10-27', firma: 'F', typ: 'NOVÉ'},
    {id: 2, datum: '2026-10-27', firma: 'F', typ: 'PŘEVOD'}]})]);
  const [shod] = issues(vice);
  assert.equal(shod.querySelectorAll('.orv-kandidat').length, 2);
  assert.deepEqual(shod.querySelectorAll('.orv-kandidat').flatMap(row => row.querySelectorAll('button'))
    .map(b => b.dataset.ukon), ['1', '2']);
  // The candidate list says it all — no repeated "Více shod" paragraph.
  assert.equal(shod.querySelector('.orv-message'), null);
});

test('written cards go to Zapsáno in scan order and review cards to their sections', () => {
  const root = render([photo(1, 'doplneno', {ukon: {id: 1, firma_zkratka: 'JN', firma_id: 14,
    typ: 'PŘEVOD', celkem: 1300}}), photo(2, 'bez_firmy', {rz: '2AA2222'}),
    photo(3, 'necitelne'), photo(4, 'zalozeno', {ukon: {id: 2, firma_zkratka: 'BS', firma_id: 15,
      typ: 'NOVÉ', celkem: 950}})]);
  assert.deepEqual(cards(root).map(c => c.dataset.photo), ['4', '1']);
  assert.deepEqual(unassigned(root).map(c => c.dataset.photo), ['2']);
  assert.deepEqual(issues(root).map(c => c.dataset.photo), ['3']);
  assert.equal(root.querySelector('#orv-review').hidden, false);
  assert.equal(root.querySelector('#orv-written').hidden, false);
  // Only written cards carry the "open and edit" action.
  assert.equal(unassigned(root)[0].querySelector('.orv-open-written'), null);
});

// helper: simple class check on a fake node
function hasClass(node, cls) {
  return node && String(node.className || '').split(/\s+/).includes(cls);
}

// -- 2026-11-11: a plate that disagrees with evidence is a question -------------
// 2BP1720: Petr had typed WBP1720; the photo said 2BP1720, the stored plate was
// kept as a "misread" and the card sat under ✓ Beze změny. Nobody saw it and
// the car hid from search.
test('a kept plate puts the card under Zkontroluj, never under Beze změny', () => {
  const kept = photo(1, 'uz_doplneno', {rz_ponechano: {evidence: 'WBP1720', foto: '2BP1720'},
    ukon: {id: 1687, celkem: 1800, typ: 'PŘEVOD', firma_id: 14}});
  const fine = photo(2, 'uz_doplneno', {ukon: {id: 1680}});
  assert.equal(R.needsAction(kept), true);
  assert.deepEqual(R.reviewPhotos([kept, fine]).map(p => p.id), [1]);
  assert.deepEqual(R.writtenPhotos([kept, fine]).map(p => p.id), [2]);
  assert.deepEqual(R.totals([kept, fine]), {zalozeno: 0, doplneno: 0, uz_doplneno: 1, review: 1, necitelne: 0});
  assert.equal(R.bannerState([kept, fine]).tone, 'warn');
  const root = render([kept, fine]);
  assert.deepEqual(issues(root).map(c => c.dataset.photo), ['1']);
  const text = plain(allText(issues(root)[0]));
  assert.ok(text.includes('Ke kontrole') && text.includes('WBP1720') && text.includes('2BP1720'), text);
  assert.ok(text.includes('Otevřít a upravit úkon'), text);
});
