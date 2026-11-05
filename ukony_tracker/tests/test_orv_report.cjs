const {test} = require('node:test');
const assert = require('node:assert/strict');
const R = require('../static/js/orv_report.js');

const photo = (id, stav, extra = {}) => ({id, result: {stav, ...extra}});

// Minimal stand-in for the two batch <select>s the selection reads.
function mockRoot({shown = true, firma = '', typ = '', button = null, data = null} = {}) {
  const nodes = {
    '#orv-batch': {hidden: !shown},
    '#orv-batch-firma': {value: firma},
    '#orv-batch-typ': {value: typ},
  };
  if (button) nodes['#orv-create-unmatched'] = button;
  if (data !== null) nodes['#orv-data'] = {textContent: data};
  return {querySelector: sel => (Object.hasOwn(nodes, sel) ? nodes[sel] : null)};
}
const kc = n => new Intl.NumberFormat('cs-CZ', {maximumFractionDigits: 0}).format(n) + ' Kč';

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

test('summary chips count created, filled, unchanged, review and unreadable cars', () => {
  assert.deepEqual(R.totals(['zalozeno', 'doplneno', 'uz_doplneno', 'bez_firmy', 'jiz_v_evidence', 'necitelne']
    .map((state, id) => photo(id, state))),
    {zalozeno: 1, doplneno: 1, uz_doplneno: 1, review: 2, necitelne: 1});
});

test('Czech car and create-button plurals handle one, two to four and five plus', () => {
  assert.deepEqual([1, 2, 4, 5].map(R.czechCars), ['auto', 'auta', 'auta', 'aut']);
  assert.deepEqual([1, 2, 4, 5].map(R.czechJobs), ['úkon', 'úkony', 'úkony', 'úkonů']);
});

test('the duplicate warning names the existing úkon, its price and payment', () => {
  assert.equal(R.existingLine({id: 1537, datum: '2026-10-27', firma: 'JE & NE', typ: 'PŘEVOD',
    celkem: 1300, stav_platby: 'zaplaceno', poznamka: 'ACC'}),
  '#1537 · 27. 10. 2026 · PŘEVOD · JE & NE · Zaplaceno');
  assert.equal(R.existingLine({id: 7}), '#7');
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

test('one car gets one firm choice; the shared bar only fills 2+ cars', () => {
  const cars = [photo(1, 'bez_firmy'), photo(2, 'bez_firmy')];
  // 2 cars, nothing chosen yet → nothing to create.
  assert.deepEqual(R.selected(mockRoot({firma: '', typ: ''}), cars), []);
  // Shared firma+typ applies to cars that did not override it.
  assert.deepEqual(R.selected(mockRoot({firma: '3', typ: 'NOVÉ'}), cars)
    .map(x => [x.photo.id, x.firma_id, x.typ_kod]), [[1, '3', 'NOVÉ'], [2, '3', 'NOVÉ']]);
  // Per-car override wins over the shared bar.
  cars[0].firmaOverride = '7';
  assert.deepEqual(R.selected(mockRoot({firma: '3', typ: 'NOVÉ'}), cars)
    .map(x => [x.photo.id, x.firma_id]), [[1, '7'], [2, '3']]);
  // Single car: the shared bar is hidden, so only its own choice counts.
  const single = [photo(9, 'bez_firmy')];
  assert.deepEqual(R.selected(mockRoot({shown: false, firma: '3', typ: 'NOVÉ'}), single), []);
  single[0].firmaOverride = '14'; single[0].typOverride = 'PŘEVOD';
  assert.deepEqual(R.selected(mockRoot({shown: false, firma: '3', typ: 'NOVÉ'}), single)
    .map(x => [x.firma_id, x.typ_kod]), [['14', 'PŘEVOD']]);
});

test('a duplicate car is not counted until "Přesto založit nový úkon" is checked', () => {
  const car = photo(1, 'bez_firmy', {existujici: [{id: 1537}], vyzaduje_potvrzeni: true});
  const root = mockRoot({firma: '3', typ: 'NOVÉ'});
  assert.deepEqual(R.selected(root, [car]), []);
  car.potvrdit = true;
  const chosen = R.selected(root, [car]);
  assert.equal(chosen.length, 1);
  assert.equal(R.payload(car, chosen[0]).potvrdit_novy, true);
  // The same car coming back as jiz_v_evidence after submit is excluded again.
  car.result = {stav: 'jiz_v_evidence', existujici: [{id: 1537}]};
  car.potvrdit = false;
  assert.deepEqual(R.selected(root, [car]), []);
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
  const button = {textContent: '', disabled: true, hidden: true};
  const root = mockRoot({firma: '3', typ: 'NOVÉ', button});
  const cars = [photo(1, 'bez_firmy', {rz: '1AA1111'}), photo(2, 'necitelne'),
    photo(3, 'bez_firmy', {existujici: [{id: 9}]})];
  assert.equal(R.updateCreateCount(root, cars), 1);
  assert.equal(button.textContent, 'Založit 1 úkon');
  assert.equal(button.disabled, false);
  assert.equal(button.hidden, false);
  cars[2].firmaOverride = '5'; cars[2].typOverride = 'NOVÉ'; cars[2].potvrdit = true;
  assert.equal(R.updateCreateCount(root, cars), 2);
  assert.equal(button.textContent, 'Založit 2 úkony');
  // Nothing to create → the button disappears (the form only shows issues).
  assert.equal(R.updateCreateCount(root, [photo(9, 'necitelne')]), 0);
  assert.equal(button.hidden, true);
});

test('a car rejected as already in evidence keeps its card and drops the stale check', () => {
  const first = {id: 1, result: {stav: 'bez_firmy'}, potvrdit: true, firmaOverride: '14',
    typOverride: 'NOVÉ', poznamka: 'ACC'};
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

test('ceny come from the fragment JSON block and a missing/broken block is empty', () => {
  const ceny = {'14': {'NOVÉ': 1300}};
  assert.deepEqual(R.cenyOf(mockRoot({data: JSON.stringify({ceny})})), ceny);
  assert.deepEqual(R.cenyOf(mockRoot({data: '{"ceny": null}'})), {});
  assert.deepEqual(R.cenyOf(mockRoot({data: '{broken'})), {});
  assert.deepEqual(R.cenyOf(mockRoot({})), {});
});

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
  assert.equal(R.earlier({predchozi: {id: 883, datum: '2026-08-26', firma: 'JE & NE', typ: 'PŘEVOD'}}),
    'Dříve 26. 8. 2026 · JE & NE · PŘEVOD');
  assert.equal(R.earlier({}), null);
  assert.equal(R.earlier({predchozi: {datum: 'ne-datum'}}), null);
});

test('candidate úkony for vice_shod/konflikt are capped at five', () => {
  const candidates = Array.from({length: 7}, (_, i) => ({id: i + 1, datum: '2026-10-27',
    firma: 'F', typ: 'NOVÉ', stav_platby: 'nezaplaceno'}));
  assert.deepEqual(R.kandidati({kandidati: candidates}).map(v => v.id), [1, 2, 3, 4, 5]);
  assert.deepEqual(R.kandidati({kandidati: [{id: null}, {id: 3}]}).map(v => v.id), [3]);
  assert.deepEqual(R.kandidati({}), []);
  assert.match(R.existingLine(candidates[0]), /^#1 · 27\. 10\. 2026 · NOVÉ · F · Nezaplaceno$/);
});
