// Tisk / Sdílet kódem (2.8): the share icon on a doklad row opens a small
// sheet with two choices. Tisk opens žádosti's A5 print page; Sdílet kódem
// asks evidence (POST /doklady/<n>/sdilet → žádosti) for a code, copies the
// link and offers the system share sheet — the same flow as in žádosti.
(function () {
  var sheet = document.getElementById('doklad-share');
  if (!sheet) return;
  var base = sheet.getAttribute('data-tisk-base') || '';
  var baseFaktura = sheet.getAttribute('data-tisk-base-faktura') || '';
  var druhEl = sheet.querySelector('[data-share-druh]');
  var q = function (sel) { return sheet.querySelector(sel); };
  var cisloEl = q('[data-share-cislo]'), subEl = q('[data-share-sub]');
  var choices = q('[data-share-choices]'), tisk = q('[data-share-tisk]'), kodBtn = q('[data-share-kod]');
  var result = q('[data-share-result]'), urlEl = q('[data-share-url]'), stav = q('[data-share-stav]');
  var errorEl = q('[data-share-error]');
  var cislo = null, druh = 'ppd', link = '', busy = false, serial = 0, lastFocused = null, hideTimer = null;

  function showError(msg) { errorEl.textContent = msg || ''; errorEl.hidden = !msg; }
  function text(item, sel) {
    var n = item && item.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : '';
  }

  function open(btn) {
    var item = btn.closest('.doklad-item');
    cislo = btn.getAttribute('data-doklad-share');
    druh = btn.getAttribute('data-druh') === 'faktura' ? 'faktura' : 'ppd';
    if (druhEl) druhEl.textContent = druh === 'faktura' ? 'Faktura' : 'Doklad';
    lastFocused = btn;
    ++serial; busy = false; link = '';
    cisloEl.textContent = cislo;
    subEl.textContent = [text(item, '.doklad-firma-chip'), text(item, '.doklad-kc'), text(item, '.doklad-od')]
      .filter(Boolean).join(' · ');
    tisk.href = (druh === 'faktura' ? baseFaktura : base) + encodeURIComponent(cislo);
    choices.hidden = false; result.hidden = true; showError('');
    kodBtn.disabled = false; kodBtn.removeAttribute('aria-busy');
    clearTimeout(hideTimer);  // reopened within the close animation: stay open
    sheet.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(function () { sheet.classList.add('is-open'); tisk.focus(); });
  }
  function close() {
    if (sheet.hidden) return;
    ++serial;
    sheet.classList.remove('is-open');
    document.body.classList.remove('modal-open');
    hideTimer = setTimeout(function () { sheet.hidden = true; }, 220);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function copy(url) {
    if (!navigator.clipboard || !navigator.clipboard.writeText) return Promise.reject(new Error('no clipboard'));
    return navigator.clipboard.writeText(url);
  }
  function showCode(data) {
    link = data.url;
    urlEl.textContent = link.replace(/^https?:\/\//, '');
    var platnost = 'platí ' + (data.plati_dni || 30) + ' dní';
    stav.textContent = platnost;
    choices.hidden = true; result.hidden = false;
    q('[data-share-send]').focus();
    // Copied straight away, like in žádosti: the sheet stays for reading it out.
    copy(link).then(function () { stav.textContent = 'Zkopírováno ✓ · ' + platnost; },
                    function () { stav.textContent = 'Opiš ho z displeje · ' + platnost; });
  }
  function requestCode() {
    if (busy || !cislo) return;
    var my = ++serial;
    busy = true; showError('');
    kodBtn.disabled = true; kodBtn.setAttribute('aria-busy', 'true');
    fetch('/doklady/' + encodeURIComponent(cislo) + '/sdilet', {
      method: 'POST', headers: {'X-Requested-With': 'fetch'}
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return {ok: r.ok, d: d}; });
    }).then(function (res) {
      if (my !== serial) return;
      busy = false; kodBtn.disabled = false; kodBtn.removeAttribute('aria-busy');
      if (!res.ok || !res.d.ok || !res.d.url) { showError(res.d.error || 'Kód se nepodařilo vytvořit.'); return; }
      showCode(res.d);
    }).catch(function () {
      if (my !== serial) return;
      busy = false; kodBtn.disabled = false; kodBtn.removeAttribute('aria-busy');
      showError('Spojení selhalo. Kód se nevytvořil.');
    });
  }
  // Odeslat: the phone's own share sheet (SMS / WhatsApp / mail); a desktop
  // browser has none, so it copies the link instead.
  function send() {
    if (!link) return;
    if (navigator.share) { navigator.share({text: link}).catch(function () {}); return; }
    copy(link).then(function () { stav.textContent = 'Zkopírováno ✓'; },
                    function () { window.prompt('Zkopíruj odkaz ručně:', link); });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-doklad-share]');
    if (btn) { e.preventDefault(); open(btn); return; }
    if (sheet.hidden) return;
    if (e.target === sheet || e.target.closest('[data-share-close]')) { close(); return; }
    if (e.target.closest('[data-share-kod]')) { requestCode(); return; }
    if (e.target.closest('[data-share-send]')) { send(); return; }
    if (e.target.closest('[data-share-tisk]')) setTimeout(close, 0);  // the link opens its own tab
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !sheet.hidden) close(); });
})();
