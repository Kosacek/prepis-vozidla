(function () {
  let active;
  const H = window.OrvHelpers;
  const ok = r => r && ['doplneno', 'uz_doplneno'].includes(r.stav);
  function mount(root) {
    const el = id => root.querySelector('#orv-' + id);
    let photos = [], running = false, dead = false, closing = false, imported = false;
    let processed = false, serial = 0;
    const thinking = window.Thinking(el('thinking'), el('verb'));
    function notice(text) { el('note').textContent = text; el('note').hidden = !text; }
    function controls() {
      el('counter').textContent = H.photoCount(photos.length);
      el('process').textContent = H.processLabel(photos.length);
      el('process').disabled = !photos.length || running || imported;
      el('shutter').disabled = photos.length >= 30 || imported;
      root.querySelectorAll('input[type=file]').forEach(i => { i.disabled = imported || photos.length >= 30; });
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
    root.querySelectorAll('input[type=file]').forEach(input => input.addEventListener('change', async function () {
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
        photo.retry = document.createElement('button'); photo.retry.className = 'btn';
        photo.retry.type = 'button'; photo.retry.textContent = 'Zkusit znovu';
        photo.retry.addEventListener('click', () => run([photo]));
        body.append(photo.chip, photo.text, photo.retry);
        photo.row.append(img, body); el('results').append(photo.row);
      }
      const r = photo.result;
      const state = r ? (ok(r) ? 'ok' : r.stav === 'chyba' || r.stav === 'necitelne' ? 'error' : 'warn') : 'pending';
      photo.row.dataset.state = state;
      photo.chip.textContent = r ? (ok(r) ? '✓ Hotovo' : state === 'error' ? '✗ Nezdařilo se' : '⚠ Bez změny')
        : photo.busy ? 'Čtu…' : 'Čeká';
      const u = r && r.ukon;
      const date = u && /^\d{4}-\d{2}-\d{2}$/.test(u.datum) ? u.datum.slice(8) + '.' + u.datum.slice(5, 7) + '.' : '';
      photo.text.textContent = r ? (u ? u.firma + ' · ' + date + ' — ' : '') + r.zprava : 'Fotka ' + photo.id;
      photo.retry.hidden = !r || ok(r);
      photo.retry.disabled = running;
    }
    function summary() {
      const t = H.totals(photos);
      const title = el('summary-title'); title.replaceChildren();
      const n = document.createElement('strong'); n.textContent = t.rz;
      const m = document.createElement('strong'); m.textContent = t.orv;
      title.append('Doplněno ', n, ' ' + H.plural(t.rz, 'značka', 'značky', 'značek') + ' a ',
        m, ' ' + H.plural(t.orv, 'číslo', 'čísla', 'čísel') + ' ORV');
      const labels = {uz_doplneno: 'již doplněno', nenalezeno: 'nenalezeno', vice_shod: 'více shod',
        konflikt: 'konflikt', necitelne: 'nečitelná', chyba: 'chyba'};
      el('summary-other').textContent = Object.entries(t.other).map(([k, v]) => v + ' ' + (labels[k] || k)).join(' · ');
      el('summary').hidden = false;
      el('done').hidden = false;
      el('step').textContent = '3 · Hotovo';
    }
    async function upload(photo) {
      photo.busy = true; row(photo);
      const body = new FormData();
      body.append('foto', photo.blob, 'foto');
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
      if (running || dead || imported || !queue.length) return;
      running = true; processed = true; camera.stop(); notice('');
      el('capture').hidden = el('process').hidden = el('done').hidden = el('summary').hidden = true;
      el('results').hidden = false; el('step').textContent = '2 · Zpracovávám';
      queue.forEach(p => { p.result = null; });
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
      if (closing) { window.UkonModal.close(); return; }
      summary();
    }
    function reset() {
      if (running) return;
      photos.forEach(p => URL.revokeObjectURL(p.url)); photos = [];
      el('thumbnails').replaceChildren(); el('results').replaceChildren();
      el('results').hidden = el('summary').hidden = el('done').hidden = true;
      el('capture').hidden = el('process').hidden = false;
      el('step').textContent = '1 · Foť'; controls(); camera.start();
    }
    function destroy() {
      dead = true; camera.destroy(); thinking.stop();
      photos.forEach(p => { URL.revokeObjectURL(p.url); if (p.abort) p.abort.abort(); });
      photos = [];
    }
    el('process').addEventListener('click', () => run(photos.slice()));
    el('again').addEventListener('click', reset);
    camera.start();
    return {destroy, close: function (event) {
      camera.stop();
      if (running) {
        // Finish only the (at most three) requests already sent before refresh.
        closing = true; event.preventDefault(); notice('Dokončuji rozpracované fotky…'); return;
      }
      destroy(); active = null;
      if (processed) window.location.reload();
    }};
  }
  document.addEventListener('ukon:scan-shown', function () {
    if (active) active.destroy();
    active = mount(document.getElementById('orv-sken'));
  });
  document.addEventListener('ukon:modal-closing', e => { if (active) active.close(e); });
  window.addEventListener('pagehide', function () { if (active) { active.destroy(); active = null; } });
  window.addEventListener('pageshow', function (e) {
    if (e.persisted && document.getElementById('orv-sken')) window.location.reload();
  });
})();
