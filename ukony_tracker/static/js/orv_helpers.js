(function (root) {
  function plural(n, one, few, many) { return n === 1 ? one : n >= 2 && n <= 4 ? few : many; }
  function photoCount(n) { return n + ' ' + plural(n, 'fotka', 'fotky', 'fotek'); }
  function processLabel(n) { return 'Zpracovat ' + n + ' ' + plural(n, 'fotku', 'fotky', 'fotek'); }
  function totals(photos) {
    const counts = {rz: 0, orv: 0, other: {}};
    photos.forEach(function (photo) {
      const r = photo.result;
      if (!r) return;
      if (r.stav === 'doplneno') {
        (r.doplneno || []).forEach(k => { if (k === 'rz' || k === 'orv') counts[k]++; });
      } else counts.other[r.stav] = (counts.other[r.stav] || 0) + 1;
    });
    return counts;
  }
  const api = {plural, photoCount, processLabel, totals};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OrvHelpers = api;
})(typeof window !== 'undefined' ? window : globalThis);
