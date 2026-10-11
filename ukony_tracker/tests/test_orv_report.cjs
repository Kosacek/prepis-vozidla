const {test} = require('node:test');
const assert = require('node:assert/strict');
const R = require('../static/js/orv_report.js');

const photo = (id, stav) => ({id, result: {stav}});

test('report orders review first and unreadable last, preserving order within a group', () => {
  const photos = [photo(1, 'uz_doplneno'), photo(2, 'necitelne'), photo(3, 'zalozeno'),
    photo(4, 'konflikt'), photo(5, 'doplneno'), photo(6, 'bez_firmy')];
  assert.deepEqual(R.group(photos).map(p => p.id), [4, 6, 3, 5, 1, 2]);
});

test('banner is green only when every car is readable and assigned', () => {
  assert.deepEqual(R.bannerState([photo(1, 'zalozeno'), photo(2, 'doplneno')]),
    {review: 0, text: 'Vše v pořádku', tone: 'ok'});
  assert.deepEqual(R.bannerState([photo(1, 'bez_firmy'), photo(2, 'necitelne')]),
    {review: 2, text: 'Zkontroluj 2 auta', tone: 'warn'});
  assert.deepEqual(R.bannerState([photo(1, 'konflikt')]),
    {review: 1, text: 'Zkontroluj 1 auto', tone: 'warn'});
});

test('report chips count created, filled, unchanged, review and unreadable cars', () => {
  assert.deepEqual(R.totals(['zalozeno', 'doplneno', 'uz_doplneno', 'bez_firmy', 'necitelne']
    .map((state, id) => photo(id, state))),
    {zalozeno: 1, doplneno: 1, uz_doplneno: 1, review: 1, necitelne: 1});
});

test('Czech car and create-button plurals handle one, two to four and five plus', () => {
  assert.deepEqual([1, 2, 4, 5].map(R.czechCars), ['auto', 'auta', 'auta', 'aut']);
  assert.deepEqual([1, 2, 4, 5].map(R.czechJobs), ['úkon', 'úkony', 'úkony', 'úkonů']);
});
