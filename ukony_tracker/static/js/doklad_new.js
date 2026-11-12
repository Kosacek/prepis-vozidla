// "Nový doklad" (2.6): either a firm → tick its unpaid úkony, or an IČO →
// ARES fills "Přijato od" + "Adresa na doklad". Both paths can be combined and
// the doklad can be issued with no firm and no úkon.
// The amount and the vehicles follow the ticked úkony until the user types
// their own; the payer follows the úkony too (chips from their žádosti, see
// doklad_payer.js) until the user picks a chip, types a name, types an IČO or
// lets ARES fill it.
(function () {
  var modal = document.getElementById('doklad-modal');
  if (!modal) return;
  var form = document.getElementById('doklad-new-form');
  var firma = document.getElementById('dn-firma');
  var panel = document.getElementById('dn-ukony-panel');
  var head = document.getElementById('dn-ukony-head');
  var headTitle = document.getElementById('dn-ukony-title');
  var list = document.getElementById('dn-ukony');
  var od = document.getElementById('dn-od');
  var payers = document.getElementById('dn-payers');
  var ico = document.getElementById('dn-ico');
  var aresBtn = document.getElementById('dn-ares');
  var aresStatus = document.getElementById('dn-ares-status');
  var adresa = document.getElementById('dn-adresa');
  var vozidla = document.getElementById('dn-vozidla');
  var castka = document.getElementById('dn-castka');
  var ucel = document.getElementById('dn-ucel');
  var errorEl = document.getElementById('dn-error');
  var submit = document.getElementById('dn-submit');
  var done = document.getElementById('dn-done');
  var castkaTyped = false, busy = false, issued = false, serial = 0, lastFocused = null;
  var firmaData = null, ukonyById = {}, chips = [], payerKey = null, payerChosen = false;
  // Until the user edits them, these follow the ticked úkony (amount) and the
  // payer chip (address / vehicles). ARES and a chip click count as edits.
  var vozidlaTyped = false, adresaTyped = false;
  var aresTimer = null, aresSerial = 0, aresIco = '';
  var aresCache = {}, autoSerial = 0, autoLoading = false;
  // One id per doklad, kept across retries so žádosti never issue it twice.
  var requestId = '';
  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'd-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function kc(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' Kč'; }
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
    setAresStatus('', '');  // the IČO now comes from the chip, not ARES
  }
  // A party chip means "print the address from the žádost" (žádosti holds it),
  // a firm chip carries the stored firm address. Manual typing always wins.
  // 2.8: a payer with an IČO and no known address gets it from ARES on its
  // own (David had to click ARES for Jazyková škola P.A.R.K.).
  function applyChipAdresa(chip) {
    adresa.value = chip && !chip.zadost_id ? DokladPayer.adresaText(chip) : '';
    adresa.placeholder = chip && chip.zadost_id ? 'Doplní se ze žádosti' : 'Ulice, město, PSČ';
    adresaTyped = false;
    autoAdresa(chip);
  }
  function aresFetch(d) {
    if (aresCache[d]) return Promise.resolve(aresCache[d]);
    return fetch('/firmy/ares?ico=' + encodeURIComponent(d), {headers: {'X-Requested-With': 'fetch'}})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) {
        if (!body || !body.ok) return null;
        aresCache[d] = body;
        return body;
      });
  }
  function autoAdresa(chip) {
    var my = ++autoSerial;  // any newer payer / typed address wins over this lookup
    var d = DokladPayer.aresIco(chip, adresa.value, adresaTyped);
    if (autoLoading) setAresStatus('', '');  // an older lookup's spinner never outlives it
    if (!d) return;
    if (!aresCache[d]) { setAresStatus('loading', 'Hledám adresu v ARES…'); autoLoading = true; }
    aresFetch(d).then(function (body) {
      if (my !== autoSerial || adresaTyped || adresa.value.trim()) return;
      autoLoading = false;
      if (!body) { setAresStatus('err', '✗ Adresa v ARES nenalezena'); return; }
      adresa.value = DokladPayer.adresaText(body);
      setAresStatus('ok', '✓ Adresa z ARES');
    }).catch(function () {
      if (my === autoSerial) setAresStatus('err', '✗ ARES nedostupné');
    });
  }
  function firmaColor() {
    var opt = firma.selectedIndex >= 0 ? firma.options[firma.selectedIndex] : null;
    return opt && opt.dataset.color ? opt.dataset.color : '';
  }
  function renderPayers(boxes) {
    payers.replaceChildren();
    if (!firmaData) { chips = []; return; }
    var res = DokladPayer.choices(boxes.map(function (b) { return ukonyById[b.value]; }), firmaData);
    chips = res.chips;
    if (!payerChosen) {
      var auto = chips.filter(function (c) { return c.key === res.selected; })[0];
      usePayer(auto);
      if (!adresaTyped) applyChipAdresa(auto);
    }
    var on = activeChip();
    var pressed = DokladPayer.names(on, od.value) ? on : null;
    chips.forEach(function (c) {
      var b = el('button', 'chip dn-payer');
      if (c.role === 'firma' && firmaColor()) {  // firm colour everywhere (company-colour rule)
        var dot = el('span', 'firma-dot');
        dot.style.background = firmaColor();
        b.append(dot);
      }
      b.append(c.label);
      b.type = 'button'; b.title = c.jmeno + (c.ico ? ' · IČO ' + c.ico : '');
      b.setAttribute('aria-pressed', String(c === pressed));
      b.addEventListener('click', function () {
        payerChosen = true; usePayer(c); applyChipAdresa(c); refresh();
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
    if (!vozidlaTyped) {
      vozidla.value = DokladPayer.vozidlaFromUkony(boxes.map(function (b) { return ukonyById[b.value]; }));
    }
    submit.disabled = busy || !od.value.trim() || !(parseInt(castka.value, 10) > 0);
    submit.textContent = boxes.length ? 'Vystavit doklad · ' + kc(parseInt(castka.value, 10) || 0) : 'Vystavit doklad';
  }
  function showError(msg) { errorEl.textContent = msg || ''; errorEl.hidden = !msg; }

  // -- Collapsible "Nezaplacené úkony" panel --------------------------------
  // The head counts the unpaid úkony; the paid ones without a doklad (2.8)
  // wait folded under them behind "Zaplacené bez dokladu".
  function setHead(ukony) {
    var unpaid = (ukony || []).filter(function (u) { return !u.zaplaceno; });
    var total = unpaid.reduce(function (s, u) { return s + (parseInt(u.celkem, 10) || 0); }, 0);
    headTitle.textContent = 'Nezaplacené úkony · ' + unpaid.length + ' · ' + kc(total);
  }
  function ukonRow(u) {
    var row = el('label', 'dn-ukon' + (u.zaplaceno ? ' is-paid' : ''));
    var box = el('input'); box.type = 'checkbox'; box.value = u.id; box.dataset.kc = u.celkem;
    var d = u.datum.slice(8, 10) + '.' + u.datum.slice(5, 7) + '.';
    row.append(box, el('b', 'dn-ukon__auto', u.vozidlo || '—'), el('span', 'tag', u.typ),
      el('span', 'dn-ukon__meta muted', d + (u.poznamka ? ' · ' + u.poznamka : '')),
      el('b', 'dn-ukon__kc', kc(u.celkem)));
    if (u.zaplaceno) row.title = 'Úkon je už zaplacený';
    return row;
  }
  function paidSection(paid) {
    var wrap = el('div', 'dn-paid');
    var toggle = el('button', 'dn-paid__toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.append(el('span', null, 'Zaplacené bez dokladu · ' + paid.length), el('span', 'dn-ukony__chev'));
    var rows = el('div', 'dn-paid__rows');
    rows.hidden = true;
    paid.forEach(function (u) { rows.append(ukonRow(u)); });
    toggle.addEventListener('click', function () {
      var open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      rows.hidden = !open;  // ticks survive folding
    });
    wrap.append(toggle, rows);
    return wrap;
  }
  function setPanelOpen(open) {
    head.setAttribute('aria-expanded', String(open));
    list.hidden = !open;  // ticking survives: the rows are only hidden
  }
  head.addEventListener('click', function () { setPanelOpen(head.getAttribute('aria-expanded') !== 'true'); });

  // -- ARES lookup ----------------------------------------------------------
  function setAresStatus(state, text) {
    autoLoading = false;  // whoever writes the status now owns it
    aresStatus.textContent = text || '';
    if (state) aresStatus.dataset.state = state; else delete aresStatus.dataset.state;
    aresStatus.hidden = !text;
  }
  function icoDigits() { return (ico.value || '').replace(/\D/g, ''); }
  function scheduleAres() {
    clearTimeout(aresTimer);
    ++aresSerial;  // any change invalidates a lookup already in flight
    if (icoDigits().length !== 8) { setAresStatus('', ''); return; }
    aresTimer = setTimeout(function () { lookupAres(false); }, 450);
  }
  function lookupAres(force) {
    clearTimeout(aresTimer);
    var d = icoDigits();
    if (d.length !== 8) {
      if (force) setAresStatus('err', '✗ Zadej 8 číslic IČO');
      return;
    }
    var state = aresStatus.dataset.state;
    if (!force && d === aresIco && (state === 'loading' || state === 'ok')) return;
    var my = ++aresSerial;
    aresIco = d;
    setAresStatus('loading', 'Načítám z ARES…');
    fetch('/firmy/ares?ico=' + encodeURIComponent(d), {headers: {'X-Requested-With': 'fetch'}})
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (body) {
          return {ok: r.ok, status: r.status, d: body};
        });
      })
      .then(function (res) {
        if (my !== aresSerial) return;
        if (!res.ok || !res.d || !res.d.ok) {
          setAresStatus('err', res.status === 404 ? '✗ ARES nenalezeno' : '✗ ARES nedostupné');
          return;
        }
        // The requested fix: ARES always wins over the payer chips.
        od.value = res.d.nazev || '';
        adresa.value = DokladPayer.adresaText(res.d);
        adresaTyped = false;
        payerChosen = true;
        setAresStatus('ok', '✓ ' + (res.d.nazev || 'Načteno z ARES'));
        refresh();
      })
      .catch(function () {
        if (my === aresSerial) setAresStatus('err', '✗ ARES nedostupné');
      });
  }

  // -- Úkony of the chosen firm ---------------------------------------------
  function loadUkony() {
    var my = ++serial;
    list.replaceChildren();
    // A new firm starts over: its firm is the payer until úkony say otherwise.
    firmaData = null; ukonyById = {}; payerKey = null; payerChosen = false;
    // The vehicles auto-follow the ticked úkony again (the address is a manual
    // edit and is not touched: user text always wins).
    vozidlaTyped = false; vozidla.value = '';
    setAresStatus('', '');
    showError('');
    panel.hidden = !firma.value;
    setPanelOpen(true);
    setHead([]);
    refresh();
    if (!firma.value) return;
    headTitle.textContent = 'Nezaplacené úkony';
    list.append(el('p', 'muted small', 'Načítám úkony…'));
    submit.disabled = true;  // never submit a half-loaded firm
    fetch('/doklady/novy/ukony?firma=' + encodeURIComponent(firma.value), {headers: {'X-Requested-With': 'fetch'}})
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (my !== serial) return;
        list.replaceChildren();
        firmaData = data.firma || null;
        ukonyById = {};
        (data.ukony || []).forEach(function (u) { ukonyById[u.id] = u; });
        if (firmaData && firma.selectedIndex >= 0) {
          // Fallback while the JSON lacks the address (the <option data-*>).
          var opt = firma.options[firma.selectedIndex];
          firmaData.adresa = firmaData.adresa || opt.dataset.adresa || '';
          firmaData.psc = firmaData.psc || opt.dataset.psc || '';
        }
        var all = data.ukony || [];
        var unpaid = all.filter(function (u) { return !u.zaplaceno; });
        var paid = all.filter(function (u) { return u.zaplaceno; });
        setHead(all);
        // A short list stays open; a long one starts folded to its header (the
        // count and total stay visible), so the amount and the button stay in
        // reach. The user opens it with one tap and the ticks survive folding.
        setPanelOpen(unpaid.length <= 4);
        if (!all.length) {
          list.append(el('p', 'muted small', 'Firma nemá úkony bez dokladu z posledních 90 dní.'));
        } else if (!unpaid.length) {
          list.append(el('p', 'muted small', 'Žádné nezaplacené úkony bez dokladu.'));
        }
        unpaid.forEach(function (u) { list.append(ukonRow(u)); });
        if (paid.length) list.append(paidSection(paid));
        refresh();
      })
      .catch(function () {
        if (my !== serial) return;
        list.replaceChildren(); setHead([]);
        showError('Úkony se nepodařilo načíst.');
        refresh();
      });
  }

  function open() {
    lastFocused = document.activeElement;
    form.hidden = false; done.hidden = true; issued = false; busy = false;
    castkaTyped = false; vozidlaTyped = false; adresaTyped = false;
    firmaData = null; ukonyById = {}; payerKey = null; payerChosen = false;
    clearTimeout(aresTimer); ++aresSerial; aresIco = '';
    requestId = newId();
    attachFirmaPick();  // idempotent: covers firma_pick.js loading after this file
    form.reset(); list.replaceChildren(); showError('');
    syncFirmaPick();  // form.reset() only moves the native <select>, not the picker
    panel.hidden = true; setHead([]); setPanelOpen(true);
    adresa.value = ''; vozidla.value = ''; setAresStatus('', '');
    adresa.placeholder = 'Ulice, město, PSČ'; ++autoSerial;
    refresh();
    var filter = document.querySelector('#doklady-filter select[name=firma]');
    if (filter && filter.value && firma.querySelector('option[value="' + filter.value + '"]')) {
      firma.value = filter.value;
      syncFirmaPick();  // a programmatic value throws no `change`
      loadUkony();
    }
    modal.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(function () { modal.classList.add('is-open'); focusFirma(); });
  }
  function close() {
    if (busy) return;
    modal.classList.remove('is-open');
    document.body.classList.remove('modal-open');
    setTimeout(function () { modal.hidden = true; }, 280);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    if (issued) window.location.reload();
  }

  // <option data-ico/data-nazev/data-adresa/data-psc/data-color> for the firm
  // select, from the JSON block next to the modal. Keeps the server HTML plain
  // (the no-JS fallback) and feeds both the payer chips and firma_pick.js.
  function decorateFirmOptions() {
    var box = document.getElementById('dn-firmy-data');
    if (!box) return;
    var byId = {};
    try {
      (JSON.parse(box.textContent) || []).forEach(function (f) { byId[String(f.id)] = f; });
    } catch (_) { return; }
    Array.prototype.forEach.call(firma.options, function (o) {
      var f = byId[o.value];
      if (!f) return;
      o.dataset.ico = f.ico || '';
      o.dataset.nazev = f.nazev || '';
      o.dataset.adresa = f.adresa || '';
      o.dataset.psc = f.psc || '';
      o.dataset.color = f.color || '';  // dot color for the colored picker
    });
  }
  decorateFirmOptions();

  // -- Colored firm picker (static/js/firma_pick.js) -----------------------
  // The native <select> stays the value source (and the no-JS fallback);
  // FirmaPick only renders the colored button + list and fires `change`, so
  // loadUkony() below keeps working untouched. Without firma_pick.js nothing
  // changes — the plain select keeps working.
  var firmaPick = null;
  function attachFirmaPick() {
    if (firmaPick || !firma || !window.FirmaPick || !window.FirmaPick.attach) return firmaPick;
    try { firmaPick = window.FirmaPick.attach(firma); } catch (_) { firmaPick = null; }
    return firmaPick;
  }
  function syncFirmaPick() {
    if (!firma || !window.FirmaPick || !window.FirmaPick.sync) return;
    try { window.FirmaPick.sync(firma); } catch (_) {}
  }
  function focusFirma() {
    var target = firmaPick && firmaPick.button ? firmaPick.button : firma;
    if (target && target.focus) target.focus();
  }
  attachFirmaPick();

  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-doklad-novy]')) { e.preventDefault(); open(); return; }
    if (e.target.closest('[data-doklad-close]') || e.target === modal) close();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !modal.hidden) close(); });
  firma.addEventListener('change', loadUkony);
  list.addEventListener('change', refresh);
  // Typing the payer by hand stops the automatic choice for good.
  od.addEventListener('input', function () { payerChosen = true; refresh(); });
  ico.addEventListener('input', function () { payerChosen = true; scheduleAres(); refresh(); });
  ico.addEventListener('blur', function () { lookupAres(false); });
  aresBtn.addEventListener('click', function () { lookupAres(true); });
  adresa.addEventListener('input', function () {
    adresaTyped = true; ++autoSerial;
    if (autoLoading) setAresStatus('', '');
  });
  // Typed vehicles win over the ones derived from the úkony.
  vozidla.addEventListener('input', function () { vozidlaTyped = true; });
  castka.addEventListener('input', function () { castkaTyped = castka.value !== ''; refresh(); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (submit.disabled || busy) return;
    busy = true; showError(''); refresh();
    submit.textContent = 'Vystavuji…';
    var profil = '';
    try { profil = localStorage.getItem('ukony_zpracoval') || ''; } catch (_) {}
    var payload = Object.assign({
      firma_id: firma.value ? parseInt(firma.value, 10) : null,
      ukony: ticked().map(function (b) { return parseInt(b.value, 10); }),
      prijato_od: od.value, prijato_ico: ico.value, prijato_adresa: adresa.value.trim(),
      castka: parseInt(castka.value, 10), ucel: ucel.value,
      zpracoval: profil, request_id: requestId,
      vozidla: DokladPayer.parseVozidla(vozidla.value)
    }, DokladPayer.fields(activeChip(), od.value));
    if (!payload.prijato_adresa) delete payload.prijato_adresa;  // empty = don't send
    fetch('/doklady/novy', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
      body: JSON.stringify(payload)
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
