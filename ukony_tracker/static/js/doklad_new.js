// "Nový doklad" (2.5): firm → tick its unpaid úkony → žádosti issue the doklad.
// The amount follows the ticked úkony until the user types their own; the payer
// follows them too (chips from their žádosti, see doklad_payer.js) until the
// user picks a chip or types a name.
(function () {
  var modal = document.getElementById('doklad-modal');
  if (!modal) return;
  var form = document.getElementById('doklad-new-form');
  var firma = document.getElementById('dn-firma');
  var list = document.getElementById('dn-ukony');
  var od = document.getElementById('dn-od');
  var payers = document.getElementById('dn-payers');
  var ico = document.getElementById('dn-ico');
  var castka = document.getElementById('dn-castka');
  var ucel = document.getElementById('dn-ucel');
  var errorEl = document.getElementById('dn-error');
  var submit = document.getElementById('dn-submit');
  var done = document.getElementById('dn-done');
  var castkaTyped = false, busy = false, issued = false, serial = 0, lastFocused = null;
  var firmaData = null, ukonyById = {}, chips = [], payerKey = null, payerChosen = false;
  // One id per doklad, kept across retries so žádosti never issue it twice.
  var requestId = '';
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'd-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function kc(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' Kč'; }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function ticked() {
    return Array.prototype.slice.call(list.querySelectorAll('input[type=checkbox]:checked'));
  }
  function activeChip() {
    return chips.filter(function (c) { return c.key === payerKey; })[0] || null;
  }
  function usePayer(chip) {
    payerKey = chip.key; od.value = chip.jmeno; ico.value = chip.ico;
  }
  function renderPayers(boxes) {
    payers.replaceChildren();
    if (!firmaData) { chips = []; return; }
    var res = DokladPayer.choices(boxes.map(function (b) { return ukonyById[b.value]; }), firmaData);
    chips = res.chips;
    if (!payerChosen) usePayer(chips.filter(function (c) { return c.key === res.selected; })[0]);
    var on = activeChip();
    var pressed = DokladPayer.names(on, od.value) ? on : null;
    chips.forEach(function (c) {
      var b = el('button', 'chip dn-payer', c.label);
      b.type = 'button'; b.title = c.jmeno + (c.ico ? ' · IČO ' + c.ico : '');
      b.setAttribute('aria-pressed', String(c === pressed));
      b.addEventListener('click', function () {
        payerChosen = true; usePayer(c); refresh();
        var now = payers.querySelector('[aria-pressed="true"]');  // chips re-render: keep focus
        if (now) now.focus();
      });
      payers.append(b);
    });
  }
  function refresh() {
    var boxes = ticked();
    renderPayers(boxes);
    if (!castkaTyped) {
      castka.value = boxes.reduce(function (s, b) { return s + (parseInt(b.dataset.kc, 10) || 0); }, 0) || '';
    }
    submit.disabled = busy || !boxes.length || !od.value.trim() || !(parseInt(castka.value, 10) > 0);
    submit.textContent = boxes.length ? 'Vystavit doklad · ' + kc(parseInt(castka.value, 10) || 0) : 'Vystavit doklad';
  }
  function showError(msg) { errorEl.textContent = msg || ''; errorEl.hidden = !msg; }

  function loadUkony() {
    var my = ++serial;
    list.replaceChildren();
    // A new firm starts over: its firm is the payer until úkony say otherwise.
    firmaData = null; ukonyById = {}; payerKey = null; payerChosen = false;
    showError('');
    if (!firma.value) { refresh(); return; }
    list.append(el('p', 'muted small', 'Načítám úkony…'));
    fetch('/doklady/novy/ukony?firma=' + encodeURIComponent(firma.value), {headers: {'X-Requested-With': 'fetch'}})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (my !== serial) return;
        list.replaceChildren();
        firmaData = data.firma || null;
        ukonyById = {};
        (data.ukony || []).forEach(function (u) { ukonyById[u.id] = u; });
        if (!data.ukony || !data.ukony.length) {
          list.append(el('p', 'muted small', 'Firma nemá nezaplacené úkony bez dokladu z posledních 90 dní.'));
        } else {
          list.append(el('div', 'dn-ukony__label', 'Nezaplacené úkony'));
          data.ukony.forEach(function (u) {
            var row = el('label', 'dn-ukon');
            var box = el('input'); box.type = 'checkbox'; box.value = u.id; box.dataset.kc = u.celkem;
            var d = u.datum.slice(8, 10) + '.' + u.datum.slice(5, 7) + '.';
            row.append(box, el('b', 'dn-ukon__auto', u.vozidlo || '—'), el('span', 'tag', u.typ),
              el('span', 'dn-ukon__meta muted', d + (u.poznamka ? ' · ' + u.poznamka : '')),
              el('b', 'dn-ukon__kc', kc(u.celkem)));
            list.append(row);
          });
        }
        refresh();
      })
      .catch(function () { if (my === serial) { list.replaceChildren(); showError('Úkony se nepodařilo načíst.'); } });
  }

  function open() {
    lastFocused = document.activeElement;
    form.hidden = false; done.hidden = true; issued = false; busy = false; castkaTyped = false;
    firmaData = null; ukonyById = {}; payerKey = null; payerChosen = false;
    requestId = newId();
    form.reset(); list.replaceChildren(); showError(''); refresh();
    var filter = document.querySelector('#doklady-filter select[name=firma]');
    if (filter && filter.value && firma.querySelector('option[value="' + filter.value + '"]')) {
      firma.value = filter.value; loadUkony();
    }
    modal.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(function () { modal.classList.add('is-open'); firma.focus(); });
  }
  function close() {
    if (busy) return;
    modal.classList.remove('is-open');
    document.body.classList.remove('modal-open');
    setTimeout(function () { modal.hidden = true; }, 280);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    if (issued) window.location.reload();
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-doklad-novy]')) { e.preventDefault(); open(); return; }
    if (e.target.closest('[data-doklad-close]') || e.target === modal) close();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !modal.hidden) close(); });
  firma.addEventListener('change', loadUkony);
  list.addEventListener('change', refresh);
  // Typing the payer by hand stops the automatic choice for good.
  od.addEventListener('input', function () { payerChosen = true; refresh(); });
  ico.addEventListener('input', function () { payerChosen = true; refresh(); });
  castka.addEventListener('input', function () { castkaTyped = castka.value !== ''; refresh(); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (submit.disabled || busy) return;
    busy = true; showError(''); refresh();
    submit.textContent = 'Vystavuji…';
    var profil = '';
    try { profil = localStorage.getItem('ukony_zpracoval') || ''; } catch (_) {}
    fetch('/doklady/novy', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
      body: JSON.stringify(Object.assign({
        firma_id: parseInt(firma.value, 10), ukony: ticked().map(function (b) { return parseInt(b.value, 10); }),
        prijato_od: od.value, prijato_ico: ico.value, castka: parseInt(castka.value, 10), ucel: ucel.value,
        zpracoval: profil, request_id: requestId
      }, DokladPayer.fields(activeChip(), od.value)))
    }).then(function (r) { return r.json().then(function (d) { return {ok: r.ok, d: d}; }); })
      .then(function (res) {
        busy = false;
        if (!res.ok) { showError(res.d.error || 'Doklad se nepodařilo vystavit.'); refresh(); return; }
        issued = true;
        document.getElementById('dn-done-title').textContent = '✓ Doklad č. ' + res.d.cislo + ' je vystavený';
        document.getElementById('dn-print').href = res.d.print_url;
        form.hidden = true; done.hidden = false;
      })
      .catch(function () { busy = false; showError('Spojení selhalo. Doklad se nevystavil.'); refresh(); });
  });
})();
