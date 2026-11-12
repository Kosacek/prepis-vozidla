const {test} = require('node:test');
const assert = require('node:assert/strict');
const P = require('../static/js/doklad_payer.js');

const TESLA = {nazev: 'Tesla Czech Republic s.r.o.', zkratka: 'Tesla', ico: '07738315'};
const RAIF = {jmeno: 'Raiffeisen - Leasing, s.r.o.', ico: '61467863'};
const zadost = (id, provozovatel, vlastnik) => ({id, provozovatel: provozovatel || null, vlastnik: vlastnik || null});
const ukon = (id, z) => ({id, zadost: z || null});
const keys = res => res.chips.map(c => c.role + ':' + c.jmeno);

test('owner who is also the operator is one Provozovatel chip, addressed from the owner block', () => {
  const res = P.choices([ukon(1, zadost('z1', null, {jmeno: 'Jan Novák', ico: ''}))], TESLA);
  assert.deepEqual(keys(res), ['provozovatel:Jan Novák', 'firma:Tesla Czech Republic s.r.o.']);
  assert.equal(res.chips[0].label, 'Provozovatel · Jan Novák');
  assert.equal(res.chips[0].strana, 'vlastnik');
  assert.equal(res.chips[0].zadost_id, 'z1');
  assert.equal(res.chips[1].label, 'Firma · Tesla');
  assert.equal(res.selected, res.chips[0].key);
});

test('leased car: operator, leasing owner and firm, operator preselected', () => {
  const res = P.choices([ukon(1, zadost('z1', {jmeno: 'EKOSTYREN s.r.o.', ico: '25850512'}, RAIF))], TESLA);
  assert.deepEqual(keys(res), ['provozovatel:EKOSTYREN s.r.o.', 'vlastnik:Raiffeisen - Leasing, s.r.o.',
    'firma:Tesla Czech Republic s.r.o.']);
  assert.equal(res.chips[0].strana, 'provozovatel');
  assert.equal(res.chips[1].strana, 'vlastnik');
  assert.equal(res.selected, res.chips[0].key);
});

test('operator entered separately but identical to the owner merges into one chip', () => {
  const same = {jmeno: 'KUMMER Tech a.s.', ico: '29275679'};
  const res = P.choices([ukon(1, zadost('z1', same, {jmeno: 'Kummer Tech a.s.', ico: '29 275 679'}))], TESLA);
  assert.deepEqual(keys(res), ['provozovatel:KUMMER Tech a.s.', 'firma:Tesla Czech Republic s.r.o.']);
});

test('same person on several úkony is one chip; names compare without case and spacing', () => {
  const res = P.choices([
    ukon(1, zadost('z1', null, {jmeno: 'PETR  STARÝ', ico: ''})),
    ukon(2, zadost('z2', null, {jmeno: 'Petr Starý', ico: ''})),
  ], TESLA);
  assert.equal(res.chips.length, 2);
  assert.equal(res.selected, res.chips[0].key);
});

test('different operators but a shared leasing owner preselect the owner', () => {
  const res = P.choices([
    ukon(1, zadost('z1', {jmeno: 'EKOSTYREN s.r.o.', ico: '25850512'}, RAIF)),
    ukon(2, zadost('z2', {jmeno: 'František Urban', ico: '12660825'}, RAIF)),
  ], TESLA);
  assert.equal(res.chips.find(c => c.key === res.selected).jmeno, RAIF.jmeno);
});

test('nothing shared, nothing ticked or a manual úkon in the mix falls back to the firm', () => {
  const firm = res => res.chips.find(c => c.key === res.selected).role;
  assert.equal(firm(P.choices([
    ukon(1, zadost('z1', null, {jmeno: 'Jan Novák', ico: ''})),
    ukon(2, zadost('z2', null, {jmeno: 'Eva Malá', ico: ''})),
  ], TESLA)), 'firma');
  assert.equal(firm(P.choices([], TESLA)), 'firma');
  const mixed = P.choices([ukon(1, zadost('z1', null, {jmeno: 'Jan Novák', ico: ''})), ukon(2)], TESLA);
  assert.equal(firm(mixed), 'firma');
  assert.deepEqual(keys(mixed), ['provozovatel:Jan Novák', 'firma:Tesla Czech Republic s.r.o.']);
});

test('manual úkony alone show only the firm chip', () => {
  const res = P.choices([ukon(1), ukon(2)], TESLA);
  assert.deepEqual(keys(res), ['firma:Tesla Czech Republic s.r.o.']);
});

test('a party that is the firm itself folds into the firm chip', () => {
  const res = P.choices([ukon(1, zadost('z1', null, {jmeno: 'TESLA CZECH REPUBLIC S.R.O.', ico: '07738315'}))], TESLA);
  assert.deepEqual(keys(res), ['firma:Tesla Czech Republic s.r.o.']);
  assert.equal(res.selected, res.chips[0].key);
});

test('chips are capped so a big selection stays compact', () => {
  const many = Array.from({length: 12}, (_, i) => ukon(i, zadost('z' + i, null, {jmeno: 'Osoba ' + i, ico: ''})));
  const res = P.choices(many, TESLA);
  assert.equal(res.chips.length, P.MAX_PARTY_CHIPS + 1);
  assert.equal(res.chips[res.chips.length - 1].role, 'firma');
});

test('party fields go out only while Přijato od still names that party', () => {
  const res = P.choices([ukon(1, zadost('z1', {jmeno: 'EKOSTYREN s.r.o.', ico: '25850512'}, RAIF))], TESLA);
  const [prov, , firma] = res.chips;
  assert.deepEqual(P.fields(prov, ' EKOSTYREN  s.r.o. '), {zadost_id: 'z1', strana: 'provozovatel'});
  assert.deepEqual(P.fields(prov, 'EKOSTYREN s.r.o., Brno'), {});
  assert.deepEqual(P.fields(firma, firma.jmeno), {});
  assert.deepEqual(P.fields(null, 'cokoliv'), {});
  assert.equal(P.names(firma, 'Tesla Czech Republic s.r.o.'), true);
  assert.equal(P.names(firma, 'Tesla'), false);
  assert.equal(P.names(null, ''), false);
});

test('the preselected chip survives the cap (many operators, one leasing owner)', () => {
  const many = Array.from({length: 9}, (_, i) =>
    ukon(i, zadost('z' + i, {jmeno: 'Klient ' + i, ico: String(10000000 + i)}, RAIF)));
  const res = P.choices(many, TESLA);
  assert.equal(res.chips.length, P.MAX_PARTY_CHIPS + 1);
  assert.equal(res.chips.find(c => c.key === res.selected).jmeno, RAIF.jmeno);
});

// --- 2.6: address printed under the payer + manual vehicles -----------------

test('adresaText joins the address and PSČ, never twice', () => {
  assert.equal(P.adresaText({adresa: 'Veveří 102, Brno', psc: '616 00'}), 'Veveří 102, Brno, 616 00');
  // PSČ already at the end of the address (with or without the space)
  assert.equal(P.adresaText({adresa: 'Veveří 102, Brno, 616 00', psc: '616 00'}), 'Veveří 102, Brno, 616 00');
  assert.equal(P.adresaText({adresa: 'Veveří 102, Brno, 61600', psc: '616 00'}), 'Veveří 102, Brno, 61600');
  assert.equal(P.adresaText({adresa: ' Veveří  102, Brno ', psc: ''}), 'Veveří 102, Brno');
  assert.equal(P.adresaText({adresa: '', psc: '616 00'}), '616 00');
  assert.equal(P.adresaText({adresa: 'Brno'}), 'Brno');
  assert.equal(P.adresaText(null), '');
});

test('the firm chip carries the stored address, a žádost party chip carries none', () => {
  const res = P.choices([], {...TESLA, adresa: 'Veveří 102, Brno', psc: '616 00'});
  const firm = res.chips[res.chips.length - 1];
  assert.equal(firm.role, 'firma');
  assert.equal(P.adresaText(firm), 'Veveří 102, Brno, 616 00');
  const party = P.choices([ukon(1, zadost('z1', null, {jmeno: 'Jan Novák', ico: ''}))], TESLA).chips[0];
  assert.equal(party.zadost_id, 'z1');
  assert.equal(P.adresaText(party), '');   // žádosti prints the address from the žádost
});

test('vozidlaFromUkony takes one unique id per úkon', () => {
  assert.equal(P.vozidlaFromUkony([
    {vozidlo: '3BR9309'}, {vozidlo: 'TMBER6NW0V3099310'}, {vozidlo: '3br9309'}, {vozidlo: ''},
  ]), '3BR9309, TMBER6NW0V3099310');
  // also accepts the {rz, vin} shape — the vehicle is the RZ, else the VIN
  assert.equal(P.vozidlaFromUkony([{rz: '3BR9309', vin: 'X'}, {vin: 'TMBER6NW0V3099310'}]),
    '3BR9309, TMBER6NW0V3099310');
  assert.equal(P.vozidlaFromUkony([undefined, null]), '');
  assert.equal(P.vozidlaFromUkony([]), '');
  assert.equal(P.vozidlaFromUkony(null), '');
});

test('parseVozidla splits on commas, semicolons and newlines, trims and dedupes', () => {
  assert.deepEqual(P.parseVozidla(' 3br9309 ; tmber6nw0v3099310,\n3BR9309  '),
    ['3BR9309', 'TMBER6NW0V3099310']);
  assert.deepEqual(P.parseVozidla('3BR 9309'), ['3BR 9309']);   // inner space collapses, doesn't vanish
  assert.deepEqual(P.parseVozidla(';;,\n '), []);
  assert.deepEqual(P.parseVozidla(''), []);
  assert.deepEqual(P.parseVozidla(null), []);
});

// 2.8: David picked JE & NE, the payer chip was "Jazyková škola P.A.R.K." (IČO
// 25589571) and "Adresa na doklad" stayed empty until he clicked ARES.
test('aresIco: a payer with a full IČO and no address is looked up in ARES', () => {
  const chip = {role: 'vlastnik', jmeno: 'Jazyková škola P.A.R.K. s.r.o.', ico: '25589571', zadost_id: 'z1'};
  assert.equal(P.aresIco(chip, '', false), '25589571');
  assert.equal(P.aresIco({...chip, ico: '255 895 71'}, '  ', false), '25589571');
});

test('aresIco: never over a typed or filled address, never without a full IČO', () => {
  const chip = {role: 'firma', jmeno: 'Lexus', ico: '25589571'};
  assert.equal(P.aresIco(chip, 'Branka 506/36, Brno', false), '');
  assert.equal(P.aresIco(chip, '', true), '');
  assert.equal(P.aresIco({...chip, ico: ''}, '', false), '');
  assert.equal(P.aresIco({...chip, ico: '1234'}, '', false), '');
  assert.equal(P.aresIco(null, '', false), '');
});
