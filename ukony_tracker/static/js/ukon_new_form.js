// Shared add form on the per-firm page and in the /ukony/vse overlay.
// All controls use delegation because modal fragments are inserted with innerHTML.
(function () {
  function field(form, name) { return form.elements.namedItem(name); }

  function params(form) {
    var q = new URLSearchParams();
    ['mesic', 'datum', 'rz', 'vin', 'orv', 'poznamka', 'zpracoval'].forEach(function (name) {
      var el = field(form, name);
      if (el && el.value) q.set(name, el.value);
    });
    var typ = field(form, 'typ_kod');
    if (typ && typ.value) q.set('typ', typ.value);
    var price = field(form, 'celkem');
    var selected = form.querySelector('#typ-seg span.on');
    // A default price follows the firm. A manually changed price stays typed.
    if (price && price.value && (!selected || price.value !== selected.dataset.cena)) {
      q.set('celkem', price.value);
    }
    return q;
  }

  function init(form) {
    if (!form) return;
    if (window.FirmaPick) window.FirmaPick.attachMarked(form);
    var person = field(form, 'zpracoval');
    if (person && !person.value) {
      try { person.value = localStorage.getItem('ukony_zpracoval') || ''; } catch (_) {}
    }
  }

  var switchSerial = 0;
  function switchFirma(form) {
    var sel = form.querySelector('#firma-select');
    if (!sel) return;
    var q = params(form);
    var modal = form.dataset.context === 'modal';
    var url = modal ? '/ukony/novy?modal=1&firma=' + encodeURIComponent(sel.value) + '&' + q.toString()
                    : '/ukony/' + encodeURIComponent(sel.value) + '?' + q.toString();
    var serial = ++switchSerial;
    document.body.classList.add('firma-switching');
    fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { if (!r.ok) throw new Error('http'); return r.text(); })
      .then(function (html) {
        if (serial !== switchSerial) return;
        if (modal) {
          var body = document.getElementById('ukon-modal-body');
          if (!body || !body.contains(form)) return;
          body.innerHTML = html;
          document.dispatchEvent(new CustomEvent('ukon:new-form-shown', { detail: { form: body.querySelector('#ukon-form') } }));
          return;
        }
        var doc = new DOMParser().parseFromString(html, 'text/html');
        ['.month-line', '.card.recent-card'].forEach(function (selector) {
          var old = document.querySelector(selector), fresh = doc.querySelector(selector);
          if (old && fresh) old.replaceWith(fresh);
        });
        var freshForm = doc.querySelector('#ukon-form');
        if (freshForm) {
          var freshSeg = freshForm.querySelector('#typ-seg');
          var seg = form.querySelector('#typ-seg');
          if (freshSeg && seg) seg.innerHTML = freshSeg.innerHTML;
          var price = field(form, 'celkem'), newPrice = field(freshForm, 'celkem');
          if (price && newPrice) price.value = newPrice.value;
        }
        form.action = '/ukony/' + sel.value;
        if (doc.title) document.title = doc.title;
        history.replaceState({}, '', url);
      })
      .catch(function () {
        if (serial !== switchSerial) return;
        if (!modal) { window.location.href = url; return; }
        var old = /\/ukony\/(\d+)$/.exec(form.action);
        if (old) sel.value = old[1];
        if (window.FirmaPick) window.FirmaPick.sync(sel);
        var note = form.querySelector('.ukon-new-message');
        note.textContent = 'Firmu se nepodařilo načíst.';
        note.className = 'ukon-new-message error';
        note.hidden = false;
      })
      .then(function () { if (serial === switchSerial) document.body.classList.remove('firma-switching'); });
  }

  document.addEventListener('ukon:new-form-shown', function (e) { init(e.detail.form); });
  init(document.querySelector('#ukon-form'));
  var entryRz = document.querySelector('#ukon-form[data-context="entry"] #rz');
  if (entryRz) entryRz.focus();

  // An edited payment or row can change the per-firm month total.
  document.addEventListener('ukon:saved', function () {
    var form = document.querySelector('#ukon-form[data-context="entry"]');
    if (!form) return;
    setTimeout(function () {
      var sel = form.querySelector('#firma-select');
      fetch('/ukony/' + sel.value + '?' + params(form).toString(), {
        headers: { 'X-Requested-With': 'fetch' }
      })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) {
          if (!html) return;
          var fresh = new DOMParser().parseFromString(html, 'text/html').querySelector('.month-line');
          var old = document.querySelector('.month-line');
          if (old && fresh) old.replaceWith(fresh);
        })
        .catch(function () {});
    }, 1300);
  });

  document.addEventListener('click', function (e) {
    var typ = e.target.closest('#ukon-form #typ-seg span[data-kod]');
    if (typ) {
      var form = typ.closest('#ukon-form');
      form.querySelectorAll('#typ-seg span').forEach(function (s) { s.classList.remove('on'); });
      typ.classList.add('on');
      field(form, 'typ_kod').value = typ.dataset.kod;
      if (typ.dataset.cena) field(form, 'celkem').value = typ.dataset.cena;
    }
    var chip = e.target.closest('#ukon-form .chip[data-tag]');
    if (chip) {
      var note = field(chip.closest('#ukon-form'), 'poznamka');
      note.value = (note.value ? note.value + ' ' : '') + chip.dataset.tag;
    }
  });

  document.addEventListener('change', function (e) {
    var form = e.target.closest('#ukon-form');
    if (!form) return;
    if (e.target.dataset.action === 'switchFirma') switchFirma(form);
    if (e.target.name === 'zpracoval') {
      try { localStorage.setItem('ukony_zpracoval', e.target.value); } catch (_) {}
    }
  });

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('#ukon-form[data-context="modal"]');
    if (!form) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    var note = form.querySelector('.ukon-new-message');
    var rz = field(form, 'rz').value.trim();
    if (btn) btn.disabled = true;
    note.hidden = true;
    fetch(form.action, {
      method: 'POST', body: new FormData(form),
      headers: { 'X-Requested-With': 'fetch' }
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (!result.ok || !result.data.ok) throw new Error(result.data.error || 'Úkon se nepodařilo uložit.');
        if (window.ukonyAddRow) window.ukonyAddRow(result.data.html);
        if (window._orvSeen) window._orvSeen.delete(field(form, 'orv'));
        ['rz', 'vin', 'orv', 'poznamka'].forEach(function (name) { field(form, name).value = ''; });
        var status = form.querySelector('.orv-status');
        if (status) { status.style.display = 'none'; status.textContent = ''; }
        note.textContent = 'Přidáno ✓' + (rz ? ' ' + rz.toUpperCase() : '');
        note.className = 'ukon-new-message success';
        note.hidden = false;
        field(form, 'rz').focus();
      })
      .catch(function (err) {
        note.textContent = err.message || 'Úkon se nepodařilo uložit.';
        note.className = 'ukon-new-message error';
        note.hidden = false;
      })
      .then(function () { if (btn) btn.disabled = false; });
  });
})();
