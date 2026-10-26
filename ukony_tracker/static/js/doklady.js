// Doklady (2.5): a doklad opens like an FAQ entry to show the úkony it pays;
// the search box filters live like on Úkony, firma/měsíc/smazané reload the page.
(function () {
  var list = document.querySelector('.doklady-list');
  var form = document.getElementById('doklady-filter');
  if (!list || !form) return;

  list.addEventListener('click', function (e) {
    var row = e.target.closest('.doklad-row');
    if (!row) return;
    var open = row.getAttribute('aria-expanded') !== 'true';
    row.setAttribute('aria-expanded', String(open));
    var drawer = document.getElementById(row.getAttribute('aria-controls'));
    if (drawer) drawer.hidden = !open;
    row.closest('.doklad-item').classList.toggle('is-open', open);
  });

  form.querySelectorAll('select, input[type="month"]').forEach(function (el) {
    el.addEventListener('change', function () { form.submit(); });
  });

  var input = document.getElementById('doklady-search');
  var countEl = document.getElementById('doklady-count');
  var sumEl = document.getElementById('doklady-sum');
  function fold(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
  var items = Array.prototype.slice.call(list.querySelectorAll('.doklad-item'));
  items.forEach(function (it) {
    it._s = fold(it.getAttribute('data-search'));
    it._kc = parseInt(it.getAttribute('data-kc'), 10) || 0;
  });
  function apply() {
    var q = fold(input.value.trim()).replace(/\s+/g, '');
    var n = 0, sum = 0;
    items.forEach(function (it) {
      // Spaces are ignored so "3br 9309" finds 3BR9309.
      var show = !q || it._s.replace(/\s+/g, '').indexOf(q) >= 0;
      it.hidden = !show;
      if (show) { n++; sum += it._kc; }
    });
    countEl.textContent = n;
    sumEl.textContent = String(sum).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }
  if (input) input.addEventListener('input', apply);
})();
