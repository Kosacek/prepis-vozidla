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

  // The trash on an úkon row inside a doklad deletes the DOKLAD (through
  // žádosti), never the úkon. Its inline confirm() may already have refused
  // the submit (Zrušit) — then nothing happens. On failure nothing changes.
  var FAIL = 'Doklad se nepodařilo smazat.';
  list.addEventListener('submit', function (e) {
    var form = e.target.closest('form');
    if (!form || !/^\/doklady\/\d+\/smazat$/.test(form.getAttribute('action') || '')) return;
    if (e.defaultPrevented) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; });
      })
      .then(function (res) {
        if (!res.ok || !res.d.ok) { var err = new Error(res.d.error || FAIL); err.shown = true; throw err; }
        var item = form.closest('.doklad-item');
        items = items.filter(function (it) { return it !== item; });
        item.style.transition = 'opacity .15s ease';
        item.style.opacity = '0';
        setTimeout(function () { item.remove(); apply(); }, 160);
      })
      .catch(function (err) {
        if (btn) btn.disabled = false;
        window.alert(err && err.shown ? err.message : FAIL);
      });
  });
})();
