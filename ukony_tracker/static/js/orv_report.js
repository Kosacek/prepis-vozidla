(function (root) {
  const GROUPS = {konflikt: 0, vice_shod: 0, bez_firmy: 0, nenalezeno: 0, chyba: 0,
    zalozeno: 1, doplneno: 2, uz_doplneno: 3, necitelne: 4};
  const LABELS = {konflikt: 'Ke kontrole', vice_shod: 'Více shod', bez_firmy: 'Nepřiřazeno',
    nenalezeno: 'Nenalezeno', chyba: 'Chyba', zalozeno: 'Založeno', doplneno: 'Doplněno',
    uz_doplneno: 'Beze změny', necitelne: 'Nečitelné'};
  const FIELD_LABELS = {rz: 'RZ', orv: 'ORV'};
  function czechCars(n) { return n === 1 ? 'auto' : n >= 2 && n <= 4 ? 'auta' : 'aut'; }
  function czechJobs(n) { return n === 1 ? 'úkon' : n >= 2 && n <= 4 ? 'úkony' : 'úkonů'; }
  function group(photos) {
    return photos.slice().sort((a, b) => (GROUPS[a.result && a.result.stav] ?? 0) -
      (GROUPS[b.result && b.result.stav] ?? 0) || a.id - b.id);
  }
  function bannerState(photos) {
    const review = photos.filter(p => GROUPS[p.result && p.result.stav] === 0 ||
      (p.result && p.result.stav === 'necitelne')).length;
    return {review, text: review ? 'Zkontroluj ' + review + ' ' + czechCars(review) : 'Vše v pořádku',
      tone: review ? 'warn' : 'ok'};
  }
  function totals(photos) {
    const out = {zalozeno: 0, doplneno: 0, uz_doplneno: 0, review: 0, necitelne: 0};
    photos.forEach(p => {
      const state = p.result && p.result.stav;
      if (state === 'zalozeno' || state === 'doplneno' || state === 'uz_doplneno') out[state]++;
      else if (state === 'necitelne') out.necitelne++;
      else if (state) out.review++;
    });
    return out;
  }
  function el(name, cls, value) {
    const node = document.createElement(name);
    if (cls) node.className = cls;
    if (value != null) node.textContent = value;
    return node;
  }
  function detailLine(label, before, after) {
    const line = el('div', 'orv-change');
    line.append(el('strong', '', label), el('span', 'orv-change-before', before || '—'),
      el('span', 'orv-change-arrow', '→'), el('span', 'orv-change-after', after || '—'));
    return line;
  }
  function valuesFor(result) {
    const changes = result.zmeny || {};
    const keys = ['rz', 'orv'].filter(k => changes[k]);
    return keys.map(k => detailLine(FIELD_LABELS[k], changes[k].pred, changes[k].po));
  }
  function scannedFacts(result) {
    const facts = [['RZ', result.rz], ['VIN', result.vin], ['ORV', result.orv_cislo]].filter(x => x[1]);
    if (!facts.length) return null;
    const list = el('div', 'orv-facts');
    facts.forEach(([label, value]) => list.append(el('span', 'orv-fact', label + ' ' + value)));
    return list;
  }
  function card(photo, onRetry) {
    const result = photo.result || {};
    const state = result.stav || 'chyba';
    const item = el('article', 'orv-result');
    item.dataset.state = state === 'zalozeno' ? 'created' : state === 'doplneno' ? 'filled' :
      state === 'uz_doplneno' ? 'same' : state === 'necitelne' ? 'unreadable' : 'warn';
    const preview = el('button', 'orv-result-preview');
    preview.type = 'button'; preview.dataset.preview = photo.url;
    preview.setAttribute('aria-label', 'Zvětšit fotku ' + photo.id);
    const image = el('img'); image.src = photo.url; image.alt = '';
    preview.append(image);
    const body = el('div', 'orv-result-body');
    const heading = el('div', 'orv-result-heading');
    heading.append(el('span', 'orv-status', LABELS[state] || 'Ke kontrole'));
    if (result.ukon && result.ukon.id) {
      const open = el('button', 'orv-open-ukon', 'Otevřít úkon');
      open.type = 'button'; open.dataset.ukon = result.ukon.id;
      heading.append(open);
    }
    body.append(heading);
    if (state === 'konflikt' && result.konflikt) {
      const conflict = result.konflikt;
      const label = FIELD_LABELS[conflict.pole] || 'Hodnota';
      body.append(el('div', 'orv-conflict-label', label),
        el('div', 'orv-conflict', 'V evidenci: ' + (conflict.evidence || '—') +
          ' · Na fotce: ' + (conflict.foto || '—')));
    } else {
      const lines = valuesFor(result);
      lines.forEach(line => body.append(line));
      if (!lines.length && state === 'uz_doplneno') {
        const fields = [['rz', result.rz], ['orv', result.orv_cislo]].filter(x => x[1]);
        fields.forEach(([k, value]) => body.append(detailLine(FIELD_LABELS[k], value, value)));
      }
    }
    if (state === 'zalozeno' && result.ukon) {
      const u = result.ukon;
      const price = new Intl.NumberFormat('cs-CZ', {maximumFractionDigits: 0}).format(u.celkem || 0);
      body.append(el('div', 'orv-created', 'Nový úkon · ' + u.firma + ' · ' + u.typ + ' · ' + price + ' Kč'));
      if (result.typ_nahrada) body.append(el('div', 'orv-type-fallback', result.zprava));
    } else if (state === 'bez_firmy') {
      const facts = scannedFacts(result); if (facts) body.append(facts);
      body.append(el('div', 'orv-unmatched-owner', result.provozovatel || 'Provozovatel neuveden'));
    } else if (state === 'vice_shod' || state === 'nenalezeno' || state === 'necitelne' || state === 'chyba') {
      if (state === 'vice_shod' || state === 'nenalezeno') {
        const facts = scannedFacts(result); if (facts) body.append(facts);
      }
      body.append(el('div', 'orv-result-message', result.zprava || LABELS[state]));
    }
    if (!['zalozeno', 'doplneno', 'uz_doplneno'].includes(state)) {
      const retry = el('button', 'btn orv-retry', 'Zkusit znovu');
      retry.type = 'button'; retry.addEventListener('click', () => onRetry && onRetry(photo));
      body.append(retry);
    }
    item.append(preview, body);
    return item;
  }
  function render(rootEl, photos, onRetry) {
    const t = totals(photos), banner = bannerState(photos);
    const title = rootEl.querySelector('#orv-summary-title');
    title.textContent = (banner.tone === 'warn' ? '⚠ ' : '✓ ') + banner.text;
    title.dataset.tone = banner.tone;
    const counts = rootEl.querySelector('#orv-counts'); counts.replaceChildren();
    [[t.zalozeno, '✚ Založeno'], [t.doplneno, '✎ Doplněno'],
      [t.uz_doplneno, '✓ Beze změny'], [t.review, '⚠ Ke kontrole'],
      [t.necitelne, '✗ Nečitelné']].forEach(([n, label]) => {
      const chip = el('span', 'orv-count-chip', label + ' · ' + n);
      counts.append(chip);
    });
    const results = rootEl.querySelector('#orv-results'); results.replaceChildren();
    group(photos).forEach(photo => results.append(card(photo, onRetry)));
    renderUnassigned(rootEl, photos);
  }
  function renderUnassigned(rootEl, photos) {
    const form = rootEl.querySelector('#orv-assign');
    const rows = rootEl.querySelector('#orv-unassigned');
    rows.replaceChildren();
    const missing = photos.filter(p => p.result && p.result.stav === 'bez_firmy');
    form.hidden = !missing.length;
    missing.forEach(photo => {
      const result = photo.result;
      const row = el('div', 'orv-unassigned-row');
      const name = result.rz || result.vin || 'Bez RZ/VIN';
      row.append(el('div', 'orv-unassigned-car', name +
        (result.orv_cislo ? ' · ORV ' + result.orv_cislo : '') +
        (result.provozovatel ? ' · ' + result.provozovatel : '') + ' · Nepřiřazeno'));
      const select = el('select', 'orv-car-firma');
      select.setAttribute('aria-label', 'Firma pro ' + name);
      const inherit = el('option', '', 'Použít společnou firmu'); inherit.value = '';
      select.append(inherit);
      rootEl.querySelectorAll('#orv-batch-firma option').forEach(opt => {
        if (!opt.value) return;
        const clone = el('option', '', opt.textContent); clone.value = opt.value;
        if (String(photo.firmaOverride || '') === clone.value) clone.selected = true;
        select.append(clone);
      });
      select.addEventListener('change', () => { photo.firmaOverride = select.value || null; updateCreateCount(rootEl, photos); });
      row.append(select); rows.append(row);
    });
    updateCreateCount(rootEl, photos);
  }
  function selected(rootEl, photos) {
    const firm = rootEl.querySelector('#orv-batch-firma').value;
    const typ = rootEl.querySelector('#orv-batch-typ').value;
    return photos.filter(p => p.result && p.result.stav === 'bez_firmy').map(p => ({photo: p,
      firma_id: p.firmaOverride || firm, typ_kod: typ})).filter(x => x.firma_id);
  }
  function updateCreateCount(rootEl, photos) {
    const count = selected(rootEl, photos).length;
    const button = rootEl.querySelector('#orv-create-unmatched');
    button.textContent = 'Založit ' + count + ' ' + czechJobs(count);
    button.disabled = count === 0;
  }
  const api = {czechCars, czechJobs, group, bannerState, totals, render, selected, updateCreateCount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OrvReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
