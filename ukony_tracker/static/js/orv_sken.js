(function () {
  let active;
  const H = window.OrvHelpers;
  const REPORT = window.OrvReport;
  const ok = result => REPORT.isWritten({result});
  const LAST = window.OrvLast;
  const FINISHING = 'Dokončuji zpracování…';
  function mount(root) {
    const el = id => root.querySelector('#orv-' + id);
    let photos = [], running = false, dead = false, closing = false, imported = false;
    let processed = false, saving = false, dirty = false, serial = 0, retakePhoto = null;
    const thinking = window.Thinking(el('thinking'), el('verb'));
    // The hidden retake camera must not be treated as a batch source.
    const addInputs = () => root.querySelectorAll('input[type=file]:not(#orv-retake)');
    function notice(text) { el('note').textContent = text; el('note').hidden = !text; }
    function controls() {
      el('counter').textContent = H.photoCount(photos.length);
      el('process').textContent = H.processLabel(photos.length);
      el('process').disabled = !photos.length || running || imported;
      el('shutter').disabled = photos.length >= 30 || imported;
      addInputs().forEach(i => { i.disabled = imported || photos.length >= 30; });
    }
    function addPhoto(blob) {
      if (dead || running) return;
      if (photos.length >= 30) { notice('V jedné dávce může být nejvýše 30 fotek.'); return; }
      if (blob.size > 8 * 1024 * 1024) { notice('Fotka smí mít nejvýše 8 MB. Vyfoťte ji znovu.'); return; }
      const photo = {blob, url: URL.createObjectURL(blob), id: ++serial, result: null};
      photos.push(photo);
      const thumb = document.createElement('div');
      thumb.className = 'orv-thumb';
      const img = document.createElement('img');
      img.src = photo.url;
      img.alt = 'Fotka ' + photos.length;
      img.onerror = () => { img.hidden = true; };
      photo.thumbEl = img;
      const number = document.createElement('span');
      number.textContent = photos.length;
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '×';
      remove.setAttribute('aria-label', 'Odebrat fotku ' + photos.length);
      remove.addEventListener('click', function () {
        if (running || imported) return;
        photos = photos.filter(p => p !== photo);
        URL.revokeObjectURL(photo.url); thumb.remove(); controls();
      });
      thumb.append(img, number, remove);
      el('thumbnails').append(thumb);
      el('thumbnails').scrollLeft = el('thumbnails').scrollWidth;
      controls();
    }
    const camera = window.OrvCamera(root, addPhoto, notice);
    root.querySelectorAll('input[type=file]:not(#orv-retake)').forEach(input => input.addEventListener('change', async function () {
      const files = Array.from(input.files || []);
      input.value = ''; // Rearm native capture, including selecting the same file.
      if (imported || running || dead) return;
      imported = true; controls();
      try {
        for (const file of files) {
          if (dead) break;
          if (photos.length >= 30) { notice('V jedné dávce může být nejvýše 30 fotek.'); break; }
          addPhoto(await window.OrvFile(file, camera));
        }
      } finally { imported = false; if (!dead) controls(); }
    }));
    function row(photo) {
      if (!photo.row) {
        photo.row = document.createElement('div'); photo.row.className = 'orv-result';
        const img = document.createElement('img'); img.src = photo.url; img.alt = '';
        img.onerror = () => { img.hidden = true; };
        photo.chip = document.createElement('span'); photo.chip.className = 'orv-status';
        photo.text = document.createElement('p');
        const body = document.createElement('div'); body.className = 'orv-result-body';
        body.append(photo.chip, photo.text);
        photo.row.append(img, body); el('results').append(photo.row);
      }
      const r = photo.result;
      const state = r ? (ok(r) ? 'ok' : r.stav === 'chyba' || r.stav === 'necitelne' ? 'error' : 'warn') : 'pending';
      photo.row.dataset.state = state;
      photo.chip.textContent = r ? (ok(r) ? '✓ Hotovo' : state === 'error' ? '✗ Nezdařilo se' : '⚠ Bez změny')
        : photo.busy ? 'Čtu…' : 'Čeká';
      const u = r && r.ukon;
      const date = u && /^\d{4}-\d{2}-\d{2}$/.test(u.datum) ? u.datum.slice(8) + '.' + u.datum.slice(5, 7) + '.' : '';
      photo.text.textContent = r ? (u ? u.firma + ' · ' + date + ' — ' : '') +
        (r.zprava || REPORT.LABELS[r.stav] || '') : 'Fotka ' + photo.id;
    }
    // Znovu vyfocení: nová fotka nahradí tu v kartě a hned se přečte.
    function requestRetake(photo) {
      if (running || saving || dead || imported || !photo) return;
      retakePhoto = photo;
      const input = el('retake');
      input.value = '';
      input.click();
    }
    el('retake').addEventListener('change', async function () {
      const file = (this.files || [])[0];
      this.value = '';
      const photo = retakePhoto;
      retakePhoto = null;
      if (!file || !photo || dead || running || saving) return;
      imported = true; controls();
      let blob;
      try { blob = await window.OrvFile(file, camera); }
      catch (_) { return; }
      finally { imported = false; if (!dead) controls(); }
      if (dead || !blob) return;
      if (blob.size > 8 * 1024 * 1024) { notice('Fotka smí mít nejvýše 8 MB. Vyfoť ji znovu.'); return; }
      if (photos.indexOf(photo) < 0) return;
      URL.revokeObjectURL(photo.url);
      photo.blob = blob;
      photo.url = URL.createObjectURL(blob);
      photo.thumb = null;
      photo.result = null;
      photo.upraveno = false;
      photo.potvrdit = false;
      if (photo.thumbEl) { photo.thumbEl.hidden = false; photo.thumbEl.src = photo.url; }
      await run([photo]);
    });
    function warnBeforeUnload(event) {
      event.preventDefault();
      event.returnValue = true;
    }
    function syncUnloadGuard() {
      if (running || saving || dirty || REPORT.closePending(photos)) {
        window.addEventListener('beforeunload', warnBeforeUnload);
      } else {
        window.removeEventListener('beforeunload', warnBeforeUnload);
      }
    }
    function persist() {
      if (LAST.save(photos)) dirty = false;
      syncUnloadGuard();
    }
    function decide(photo, changes) {
      if (saving || running || dead) return;
      Object.assign(photo, changes);
      photo.createError = null;
      dirty = true;
      notice('');
      summary();
    }
    const actions = {
      onRetry: photo => run([photo]),
      onRetake: photo => requestRetake(photo),
      onDraft: () => { dirty = true; syncUnloadGuard(); },
      onWrite: photo => writeExisting(photo),
      onNew: photo => decide(photo, {novyUkon: true}),
      onBack: photo => decide(photo, {novyUkon: false}),
      onSkip: photo => decide(photo, {novyUkon: false, result: {
        ...photo.result, stav: 'preskoceno', zmeny: {}, zprava: 'Přeskočeno'}}),
    };
    function summary(save = true) {
      photos.forEach(photo => { photo.row = null; photo.retry = null; });
      REPORT.render(root, photos, actions);
      el('capture').hidden = el('process').hidden = true;
      el('summary').hidden = false;
      el('results').hidden = false;
      const pending = REPORT.reviewPhotos(photos).length;
      el('done').hidden = false;
      el('again').hidden = pending > 0;
      el('last').hidden = true;
      el('step').textContent = pending ? '3 · Zkontroluj a doplň' : '4 · Hotovo';
      if (save) persist();
      else syncUnloadGuard();
    }
    // Uložení v editaci → karta auta dostane „Upraveno" a report se uloží znovu.
    function onSaved(event) {
      const id = String(event.detail && event.detail.id);
      let hit = false;
      photos.forEach(p => {
        if (p.result && p.result.ukon && String(p.result.ukon.id) === id) { p.upraveno = true; hit = true; }
      });
      if (hit && !running) { processed = true; summary(); }
    }
    document.addEventListener('ukon:saved', onSaved);
    function showLast() {
      const stored = LAST.load();
      if (!stored || running) return;
      camera.stop(); notice('');
      photos.forEach(p => URL.revokeObjectURL(p.url));
      el('thumbnails').replaceChildren();
      photos = stored.items.map((item, i) => ({...LAST.draftOf(item.draft),
        id: i + 1, url: item.thumb || '', thumb: item.thumb || '',
        result: item.result, upraveno: !!item.upraveno, blob: null}));
      serial = photos.length;
      summary(false);
      // Uložený sken: krok zůstává akční, jen se k němu přidá, kdy byl pořízen.
      el('step').textContent += ' · ' + LAST.label(stored.at);
    }
    function offerLast() {
      const stored = LAST.load();
      el('last').hidden = !stored;
      if (stored) el('last-time').textContent = LAST.label(stored.at);
    }
    async function upload(photo) {
      photo.busy = true; row(photo);
      const body = new FormData();
      body.append('foto', photo.blob, 'foto');
      body.append('zpracoval', el('zpracoval').value);
      const abort = new AbortController();
      photo.abort = abort;
      const timeout = setTimeout(() => abort.abort(), 90000);
      try {
        const response = await fetch('/ukony/orv-sken', {method: 'POST', body, signal: abort.signal,
          headers: {'X-Requested-With': 'fetch'}});
        if (response.redirected) throw Error('Přihlášení vypršelo. Obnovte stránku a přihlaste se.');
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Fotku se nepodařilo zpracovat.');
        if (!result.stav) throw Error('Neplatná odpověď. Zkuste to znovu.');
        photo.result = result;
      } catch (e) {
        photo.result = {stav: 'chyba', zprava: e.name === 'AbortError' || e instanceof TypeError
          ? 'Spojení se přerušilo. Zkuste to znovu.' : e.message, doplneno: []};
      } finally {
        clearTimeout(timeout); photo.abort = null; photo.busy = false;
      }
      if (!dead) {
        row(photo);
        el('progress').textContent = photos.filter(p => p.result).length + ' z ' + H.photoCount(photos.length);
      }
    }
    async function run(queue) {
      if (running || saving || dead || imported || !queue.length) return;
      running = true; processed = true; camera.stop(); notice('');
      syncUnloadGuard();
      el('capture').hidden = el('process').hidden = el('done').hidden = el('summary').hidden = true;
      el('review').hidden = true;
      el('written').hidden = false;
      el('written-title').textContent = 'Průběh zpracování';
      el('results').hidden = false;
      el('step').textContent = '2 · Zpracovávám';
      queue.forEach(p => { p.result = null; p.cardEl = null; });
      photos.forEach(row);
      el('progress').textContent = photos.filter(p => p.result).length + ' z ' + H.photoCount(photos.length);
      thinking.start();
      let next = 0;
      async function worker() {
        while (!dead && !closing && next < queue.length) await upload(queue[next++]);
      }
      await Promise.all(Array.from({length: Math.min(3, queue.length)}, worker));
      running = false;
      if (dead) return;
      thinking.stop(); photos.forEach(row);
      if (closing) {
        photos.filter(p => !p.result).forEach(p => {
          p.result = {stav: 'ceka_na_fotku'};
        });
      }
      summary();
      finishClose();
    }
    function reset() {
      if (running || saving) return;
      photos.forEach(p => URL.revokeObjectURL(p.url)); photos = [];
      retakePhoto = null;
      dirty = false;
      syncUnloadGuard();
      el('thumbnails').replaceChildren(); el('results').replaceChildren();
      el('results').hidden = el('summary').hidden = el('done').hidden = true;
      el('review').hidden = el('written').hidden = true;
      el('written-title').textContent = 'Zapsáno';
      el('capture').hidden = el('process').hidden = false;
      el('step').textContent = '1 · Foť'; controls(); offerLast(); camera.start();
    }
    function destroy() {
      dead = true; camera.destroy(); thinking.stop();
      window.removeEventListener('beforeunload', warnBeforeUnload);
      document.removeEventListener('ukon:saved', onSaved);
      photos.forEach(p => { URL.revokeObjectURL(p.url); if (p.abort) p.abort.abort(); });
      photos = [];
    }
    el('process').addEventListener('click', () => run(photos.slice()));
    el('again').addEventListener('click', reset);
    el('last').addEventListener('click', showLast);
    const person = el('zpracoval');
    try { person.value = localStorage.getItem('ukony_zpracoval') || ''; } catch (_) {}
    person.addEventListener('change', () => {
      try { localStorage.setItem('ukony_zpracoval', person.value); } catch (_) {}
    });
    function finishClose() {
      if (!closing || dead) return;
      closing = false;
      if (el('note').textContent === FINISHING) notice('');
      window.UkonModal.close();
    }
    async function postAction(path, payload, accept, fallback) {
      if (running || saving || dead || imported) return;
      saving = true;
      syncUnloadGuard();
      el('assign').inert = true;
      el('create-unmatched').disabled = true;
      notice('');
      try {
        const response = await fetch('/ukony/orv-sken/' + path, {method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Requested-With': 'fetch'},
          body: JSON.stringify(payload)});
        if (response.redirected) throw Error('Přihlášení vypršelo.');
        const data = await response.json().catch(() => ({}));
        if (dead) return;
        if (!response.ok) {
          if (fallback) fallback(response.status);
          throw Error(data.error || 'Zápis se nezdařil.');
        }
        accept(data);
      } catch (error) {
        if (!dead) notice(error.message || 'Zápis se nezdařil.');
      } finally {
        saving = false;
        if (!dead) {
          syncUnloadGuard();
          el('assign').inert = false;
          REPORT.updateCreateCount(root, photos);
          finishClose();
        }
      }
    }
    function writeExisting(photo) {
      const result = photo.result;
      return postAction('zapsat', {token: result.navrh_token, ukon_id: result.ukon.id},
        data => {
          if (!ok(data)) throw Error('Zápis se nezdařil.');
          processed = true;
          photo.result = data;
          summary();
        }, status => {
          if (status !== 409 && status !== 404) return;
          photo.result = {...photo.result, lze_zapsat: false};
          summary();
        });
    }
    el('assign').addEventListener('submit', async event => {
      event.preventDefault();
      const chosen = REPORT.selected(photos);
      if (!chosen.length) return;
      return postAction('zalozit', {zpracoval: person.value,
        auta: chosen.map(item => REPORT.payload(item.photo, item))}, data => {
        if (!Array.isArray(data.results) || data.results.length !== chosen.length) {
          throw Error('Úkony se nepodařilo založit.');
        }
        if (data.results.some(ok)) processed = true;
        const blocked = REPORT.applyCreateResults(chosen, data.results);
        summary();
        if (blocked.length) notice(blocked[0].createError || 'Úkon se nepodařilo založit.');
      });
    });
    // „Otevřít úkon" (stávající i zapsaný) a zvětšení fotky — delegované na
    // celou sekci, protože karty jsou v obou sekcích.
    root.addEventListener('click', event => {
      const open = event.target.closest('[data-ukon]');
      if (open && window.UkonModal && window.UkonModal.openEdit) {
        window.UkonModal.openEdit(open.dataset.ukon);
        return;
      }
      const thumb = event.target.closest('[data-preview]');
      if (thumb) {
        const dialog = el('preview');
        dialog.querySelector('img').src = thumb.dataset.preview;
        dialog.showModal();
      }
    });
    el('preview').querySelector('.orv-preview-close').addEventListener('click', () => el('preview').close());
    el('preview').addEventListener('keydown', event => {
      if (event.key === 'Escape') event.stopPropagation();
    });
    offerLast();
    camera.start();
    return {destroy, close: function (event) {
      if (running || saving) {
        closing = true; event.preventDefault(); notice(FINISHING); return;
      }
      const pending = REPORT.closePending(photos);
      if (pending && !window.confirm('Zavřít? ' + pending + ' ' + REPORT.czechCars(pending) +
          (pending >= 2 && pending <= 4 ? ' čekají' : ' čeká') + ' na rozhodnutí.')) {
        event.preventDefault();
        return;
      }
      if (dirty || pending) persist();
      destroy(); active = null;
      if (processed) window.location.reload();
    }};
  }
  document.addEventListener('ukon:scan-shown', function () {
    if (active) active.destroy();
    active = mount(document.getElementById('orv-sken'));
  });
  document.addEventListener('ukon:scan-navigate', function () {
    if (active) { active.destroy(); active = null; }
  });
  document.addEventListener('ukon:modal-closing', e => { if (active) active.close(e); });
  window.addEventListener('pagehide', function () { if (active) { active.destroy(); active = null; } });
  window.addEventListener('pageshow', function (e) {
    if (e.persisted && document.getElementById('orv-sken')) window.location.reload();
  });
})();
