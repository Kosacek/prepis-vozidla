const {test} = require('node:test');
const assert = require('node:assert/strict');
const H = require('../static/js/orv_helpers.js');

test('Czech plurals include zero, one, two to four and five plus', () => {
  for (const [n, word] of [[0, 'značek'], [1, 'značka'], [2, 'značky'], [4, 'značky'], [5, 'značek'], [21, 'značek']]) {
    assert.equal(H.plural(n, 'značka', 'značky', 'značek'), word);
  }
  assert.equal(H.plural(1, 'číslo', 'čísla', 'čísel'), 'číslo');
  assert.equal(H.plural(4, 'číslo', 'čísla', 'čísel'), 'čísla');
  assert.equal(H.plural(5, 'číslo', 'čísla', 'čísel'), 'čísel');
  assert.equal(H.photoCount(7), '7 fotek');
  assert.equal(H.processLabel(1), 'Zpracovat 1 fotku');
  assert.equal(H.processLabel(3), 'Zpracovat 3 fotky');
  assert.equal(H.processLabel(10), 'Zpracovat 10 fotek');
});

test('summary counts changed fields only, keeps failures and repeated photos distinct', () => {
  const photos = [
    {result: {stav: 'doplneno', doplneno: ['rz', 'orv']}},
    {result: {stav: 'doplneno', doplneno: ['rz']}},
    {result: {stav: 'uz_doplneno', doplneno: []}},
    {result: {stav: 'chyba'}}, {result: {stav: 'chyba'}}, {},
  ];
  assert.deepEqual(H.totals(photos), {rz: 2, orv: 1, other: {uz_doplneno: 1, chyba: 2}});
  photos[3].result = {stav: 'doplneno', doplneno: ['orv']};
  assert.deepEqual(H.totals(photos), {rz: 2, orv: 2, other: {uz_doplneno: 1, chyba: 1}});
});
