/* Techničák report: what the scan read, what it wrote (and where), and the
   one-off decisions a person still has to make.

   Cards are split by what the person has to do:
   - "Ke kontrole a doplnění" (#orv-review): new cars to assign (firma, typ,
     poznámka, cena) and photos that failed (duplicate guard, conflict,
     unreadable…),
   - "Zapsáno" (#orv-written): úkony the scan already wrote, with a link back.
   Pure helpers are exported for node tests; the DOM builders stay here. */
(function (root) {
  'use strict';
  const DONE = {zalozeno: 1, doplneno: 2, uz_doplneno: 3};
  const DONE_ORDER = {zalozeno: 0, doplneno: 1, uz_doplneno: 2};
  // Cars the person can still create an úkon for.
  const ASSIGN = {bez_firmy: 1, jiz_v_evidence: 1};
  const REVIEW_ORDER = {bez_firmy: 0, jiz_v_evidence: 0, konflikt: 1, vice_shod: 2,
    nenalezeno: 3, chyba: 4, necitelne: 5};
  const LABELS = {konflikt: 'Ke kontrole', vice_shod: 'Více shod', bez_firmy: 'Nové auto',
    jiz_v_evidence: 'Už v evidenci', nenalezeno: 'Nenalezeno', chyba: 'Chyba',
    zalozeno: 'Založeno', doplneno: 'Doplněno', uz_doplneno: 'Beze změny', necitelne: 'Nečitelné'};
  const PAY_LABELS = {zaplaceno: 'Zaplaceno', castecne: 'Částečně', nezaplaceno: 'Nezaplaceno'};
  const FIELD_LABELS = {rz: 'RZ', orv: 'ORV', vin: 'VIN'};
  const MAX_NOTE = 120;
  const KC = new Intl.NumberFormat('cs-CZ', {maximumFractionDigits: 0});

  function stateOf(photo) { return (photo && photo.result && photo.result.stav) || null; }
  function isWritten(photo) { return !!DONE[stateOf(photo)]; }
  function needsAction(photo) { return !!stateOf(photo) && !isWritten(photo); }
  function assignable(photo) { return !!ASSIGN[stateOf(photo)]; }

  function reviewRank(photo) {
    const state = stateOf(photo);
    return REVIEW_ORDER[state] == null ? 6 : REVIEW_ORDER[state];
  }
  function sortPhotos(photos, rank) {
    return photos.slice().sort((a, b) => rank(a) - rank(b) || (a.id || 0) - (b.id || 0));
  }
  function reviewPhotos(photos) { return sortPhotos(photos.filter(needsAction), reviewRank); }
  function writtenPhotos(photos) {
    return sortPhotos(photos.filter(isWritten), p => DONE_ORDER[stateOf(p)] || 0);
  }
  function group(photos) { return reviewPhotos(photos).concat(writtenPhotos(photos)); }

  function czechCars(n) { return n === 1 ? 'auto' : n >= 2 && n <= 4 ? 'auta' : 'aut'; }
  function czechJobs(n) { return n === 1 ? 'úkon' : n >= 2 && n <= 4 ? 'úkony' : 'úkonů'; }

  function bannerState(photos) {
    const review = reviewPhotos(photos).length;
    return {review, text: review ? 'Zkontroluj ' + review + ' ' + czechCars(review) : 'Vše v pořádku',
      tone: review ? 'warn' : 'ok'};
  }

  function totals(photos) {
    const out = {zalozeno: 0, doplneno: 0, uz_doplneno: 0, review: 0, necitelne: 0};
    photos.forEach(p => {
      const state = stateOf(p);
      if (state === 'zalozeno' || state === 'doplneno' || state === 'uz_doplneno') out[state]++;
      else if (state === 'necitelne') out.necitelne++;
      else if (state) out.review++;
    });
    return out;
  }

  function dateCs(iso) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || '')) return '';
    return Number(iso.slice(8, 10)) + '. ' + Number(iso.slice(5, 7)) + '. ' + iso.slice(0, 4);
  }
  function vinSourceLabel(source) {
    return source === 'registr' ? 'z registru' : source === 'foto' ? 'z fotky' : '';
  }
  // Everything the scan read, including what it did NOT read: an unread ORV
  // number caused the 26. 10. duplicate, so it must be visible on the card.
  function readFactsList(result) {
    if (!result) return [];
    return [
      {key: 'rz', label: 'RZ', value: result.rz || null},
      {key: 'vin', label: 'VIN', value: result.vin || null,
        source: result.vin ? vinSourceLabel(result.vin_zdroj) : ''},
      {key: 'orv', label: 'ORV', value: result.orv_cislo || null},
    ];
  }
  function factText(fact) {
    const value = fact.value || 'nepřečteno';
    return fact.label + ' ' + value + (fact.value && fact.source ? ' · ' + fact.source : '');
  }
  function earlier(result) {
    const p = result && result.predchozi;
    const date = p && dateCs(p.datum);
    if (!date) return null;
    return 'Dříve ' + [date, p.firma, p.typ].filter(Boolean).join(' · ');
  }

  // -- Money -------------------------------------------------------------
  function kc(value) {
    if (value == null || value === '') return '—';
    const n = Number(value);
    return isFinite(n) ? KC.format(n) + ' Kč' : '—';
  }
  function priceFor(ceny, firma_id, typ_kod) {
    if (firma_id == null || firma_id === '' || !typ_kod) return null;
    const byFirm = (ceny || {})[String(firma_id)];
    if (!byFirm) return null;
    const price = byFirm[typ_kod];
    return price == null || price === '' || !isFinite(Number(price)) ? null : Number(price);
  }
  function priceLabel(ceny, chosen) {
    if (!chosen.firma_id || !chosen.typ_kod) return 'Cena: —';
    return 'Cena: ' + kc(priceFor(ceny, chosen.firma_id, chosen.typ_kod));
  }
  function cenyOf(rootEl) {
    const node = rootEl && rootEl.querySelector('#orv-data');
    if (!node) return {};
    try {
      const data = JSON.parse(node.textContent || '{}');
      return (data && data.ceny) || {};
    } catch (_) { return {}; }
  }

  // -- Duplicate guard ---------------------------------------------------
  function existingList(result) {
    if (!result || !Array.isArray(result.existujici)) return [];
    return result.existujici.filter(v => v && v.id != null);
  }
  // Server can flag a duplicate without the list (older payload) — show the
  // one úkon it did send instead of an empty warning.
  function visibleExisting(result) {
    const list = existingList(result);
    if (list.length) return list;
    return result && result.ukon && result.ukon.id ? [result.ukon] : [];
  }
  function needsConfirm(photo) {
    const result = photo && photo.result;
    if (!result) return false;
    return result.stav === 'jiz_v_evidence' || !!result.vyzaduje_potvrzeni ||
      existingList(result).length > 0;
  }
  function existingLine(view) {
    if (!view) return '';
    return ['#' + view.id, dateCs(view.datum), view.typ, view.firma,
      PAY_LABELS[view.stav_platby] || ''].filter(Boolean).join(' · ');
  }

  // -- Selection & payload ----------------------------------------------
  function batchDefaults(rootEl) {
    const bar = rootEl && rootEl.querySelector('#orv-batch');
    // No bar in the DOM (tests/older template) → behave as if visible.
    if (bar && bar.hidden) return {shown: false, firma_id: '', typ_kod: ''};
    const firma = rootEl && rootEl.querySelector('#orv-batch-firma');
    const typ = rootEl && rootEl.querySelector('#orv-batch-typ');
    return {shown: true, firma_id: (firma && firma.value) || '', typ_kod: (typ && typ.value) || ''};
  }
  function effective(photo, defaults) {
    const fallback = defaults || {};
    return {firma_id: photo.firmaOverride || fallback.firma_id || '',
      typ_kod: photo.typOverride || fallback.typ_kod || ''};
  }
  function noteValue(value) {
    return String(value == null ? '' : value).trim().slice(0, MAX_NOTE);
  }
  function canCreate(photo, defaults) {
    const chosen = effective(photo, defaults);
    if (!assignable(photo) || !chosen.firma_id || !chosen.typ_kod) return false;
    // A car that is already in evidence needs an explicit "přesto založit".
    return !needsConfirm(photo) || !!photo.potvrdit;
  }
  function selected(rootEl, photos) {
    const defaults = batchDefaults(rootEl);
    return photos.filter(photo => canCreate(photo, defaults)).map(photo => {
      const chosen = effective(photo, defaults);
      return {photo, firma_id: chosen.firma_id, typ_kod: chosen.typ_kod};
    });
  }
  function payload(photo, chosen) {
    const result = (photo && photo.result) || {};
    const pick = chosen || {};
    const out = {
      rz: result.rz || null, vin: result.vin || null, orv_cislo: result.orv_cislo || null,
      provozovatel: result.provozovatel || null, vin_zdroj: result.vin_zdroj || null,
      firma_id: Number(pick.firma_id), typ_kod: pick.typ_kod || null,
      potvrdit_novy: !!(photo.potvrdit && needsConfirm(photo)),
    };
    const note = noteValue(photo.poznamka);
    if (note) out.poznamka = note;
    return out;
  }
  // The create endpoint answers per sent car. A car can still come back as
  // "already in evidence" (guard fired / raced) — keep its card and inputs,
  // drop the stale confirmation and let the warning ask again.
  function applyCreateResults(chosen, results) {
    const blocked = [];
    (chosen || []).forEach((item, i) => {
      const result = (results || [])[i];
      if (!item || !item.photo || !result) return;
      item.photo.result = result;
      if (result.stav === 'jiz_v_evidence') {
        item.photo.potvrdit = false;
        blocked.push(item.photo);
      }
    });
    return blocked;
  }
  function updateCreateCount(rootEl, photos) {
    const count = selected(rootEl, photos).length;
    const button = rootEl.querySelector('#orv-create-unmatched');
    if (!button) return count;
    button.textContent = 'Založit ' + count + ' ' + czechJobs(count);
    button.disabled = count === 0;
    button.hidden = !photos.some(assignable);
    return count;
  }
  // Live price + button count after a shed or card field changed.
  function refreshPrices(rootEl, photos) {
    const defaults = batchDefaults(rootEl);
    const ceny = cenyOf(rootEl);
    photos.forEach(photo => {
      if (!assignable(photo) || !photo.cardEl) return;
      const chosen = effective(photo, defaults);
      // A card without its own override follows the shared bar — show the
      // value it will actually use, never a stale one.
      const firma = photo.cardEl.querySelector('.orv-card-firma');
      if (firma && firma.value !== chosen.firma_id) firma.value = chosen.firma_id || '';
      const typ = photo.cardEl.querySelector('.orv-card-typ');
      if (typ && typ.value !== chosen.typ_kod) typ.value = chosen.typ_kod || '';
      const price = photo.cardEl.querySelector('.orv-card-price');
      if (price) price.textContent = priceLabel(ceny, chosen);
    });
    return updateCreateCount(rootEl, photos);
  }

  // -- DOM ---------------------------------------------------------------
  function el(name, cls, value) {
    const node = document.createElement(name);
    if (cls) node.className = cls;
    if (value != null) node.textContent = value;
    return node;
  }
  function optionEl(value, label) {
    const opt = el('option', '', label);
    opt.value = value;
    return opt;
  }
  function field(container, labelText, control) {
    const wrap = el('label', 'orv-card-field');
    wrap.append(el('span', 'orv-card-label', labelText), control);
    container.append(wrap);
    return wrap;
  }
  function carName(result) {
    return (result && (result.rz || result.vin)) || 'bez RZ i VIN';
  }
  function detailLine(label, before, after) {
    const line = el('div', 'orv-change');
    line.append(el('strong', '', label), el('span', 'orv-change-before', before || '—'),
      el('span', 'orv-change-arrow', '→'), el('span', 'orv-change-after', after || '—'));
    return line;
  }
  function valuesFor(result) {
    // Unchanged fields only add noise next to a real change.
    const changes = (result && result.zmeny) || {};
    return ['rz', 'orv', 'vin'].filter(k => changes[k] && changes[k].pred !== changes[k].po)
      .map(k => detailLine(FIELD_LABELS[k], changes[k].pred, changes[k].po));
  }
  function factsNode(result, showMissing) {
    const facts = readFactsList(result);
    if (!showMissing && !facts.some(f => f.value)) return null;
    const list = el('div', 'orv-facts');
    facts.forEach(fact => {
      if (!fact.value && !showMissing) return;
      list.append(el('span', fact.value ? 'orv-fact' : 'orv-fact orv-fact-missing', factText(fact)));
    });
    return list;
  }
  function cardShell(photo, kind, state) {
    const card = el('article', 'orv-card');
    card.id = 'orv-card-' + photo.id;
    card.dataset.kind = kind;
    card.dataset.state = state;
    card.dataset.photo = String(photo.id);
    const preview = el('button', 'orv-card-preview');
    preview.type = 'button';
    preview.dataset.preview = photo.url || '';
    preview.setAttribute('aria-label', 'Zvětšit fotku ' + photo.id);
    const image = el('img');
    image.src = photo.url || '';
    image.alt = '';
    image.addEventListener('error', () => { image.hidden = true; });
    preview.append(image);
    const body = el('div', 'orv-card-body');
    card.append(preview, body);
    photo.cardEl = card;
    return {card, body};
  }
  function cardHead(photo, opts) {
    const result = photo.result || {};
    const state = stateOf(photo);
    const heading = el('div', 'orv-card-head');
    const chips = el('span', 'orv-chips');
    const overwritten = state === 'doplneno' && (result.prepsano || []).length;
    chips.append(el('span', 'orv-status', overwritten ? 'Přepsáno' : LABELS[state] || 'Ke kontrole'));
    if (photo.upraveno) chips.append(el('span', 'orv-edited', '✓ Upraveno'));
    if (photo.potvrdit && needsConfirm(photo)) {
      chips.append(el('span', 'orv-confirmed', '✓ Potvrzeno'));
    }
    heading.append(chips);
    if (opts && opts.open && result.ukon && result.ukon.id) {
      const open = el('button', 'orv-open-ukon', 'Otevřít úkon');
      open.type = 'button';
      open.dataset.ukon = String(result.ukon.id);
      heading.append(open);
    }
    return heading;
  }
  function kandidati(result) {
    return Array.isArray(result && result.kandidati)
      ? result.kandidati.filter(v => v && v.id != null).slice(0, 5) : [];
  }
  function kandidatiNode(ctx, list) {
    const box = el('div', 'orv-kandidati');
    box.append(el('p', 'orv-kandidati-title', 'Možná jde o jedno z těchto aut — otevři a zkontroluj:'));
    list.forEach(view => {
      const row = el('div', 'orv-kandidat');
      row.append(el('span', 'orv-kandidat-line', existingLine(view)));
      const open = el('button', 'orv-open-ukon', 'Otevřít');
      open.type = 'button';
      open.dataset.ukon = String(view.id);
      row.append(open);
      box.append(row);
    });
    return box;
  }
  function duplicateBlock(ctx, photo) {
    if (!needsConfirm(photo)) return null;
    const result = photo.result || {};
    const items = visibleExisting(result);
    const box = el('div', 'orv-duplicate');
    box.setAttribute('role', 'alert');
    box.append(el('p', 'orv-duplicate-title', '⚠ Tohle auto už v evidenci je'));
    box.append(el('p', 'orv-duplicate-hint',
      'Sken ho našel dřív, než by založil druhý úkon. Zkontroluj ten existující — nový založ, jen když víš proč.'));
    const list = el('ul', 'orv-existing');
    items.forEach(view => {
      const item = el('li', 'orv-existing-item');
      item.append(el('span', 'orv-existing-line', existingLine(view)));
      const meta = [view.celkem != null ? kc(view.celkem) : '',
        view.poznamka ? 'Poznámka: ' + view.poznamka : ''].filter(Boolean).join(' · ');
      if (meta) item.append(el('span', 'orv-existing-meta', meta));
      const open = el('button', 'orv-open-existing btn', 'Otevřít existující úkon');
      open.type = 'button';
      open.dataset.ukon = String(view.id);
      item.append(open);
      list.append(item);
    });
    box.append(list);
    if (assignable(photo)) {
      const label = el('label', 'orv-confirm');
      const input = el('input', 'orv-confirm-input');
      input.type = 'checkbox';
      input.checked = !!photo.potvrdit;
      input.addEventListener('change', () => {
        photo.potvrdit = input.checked;
        if (photo.cardEl) photo.cardEl.dataset.confirmed = input.checked ? '1' : '0';
        refreshPrices(ctx.rootEl, ctx.photos);
        if (photo.cardEl) renderConfirmedChip(photo);
      });
      label.append(input, el('span', '', 'Přesto založit nový úkon'));
      box.append(label);
      if (photo.cardEl) photo.cardEl.dataset.confirmed = photo.potvrdit ? '1' : '0';
    }
    return box;
  }
  // Re-render only the "✓ Potvrzeno" chip, so the card does not jump around.
  function renderConfirmedChip(photo) {
    const head = photo.cardEl && photo.cardEl.querySelector('.orv-card-head');
    if (!head) return;
    const existing = head.querySelector('.orv-confirmed');
    if (photo.potvrdit && !existing) {
      const chips = head.querySelector('.orv-chips');
      if (chips) chips.append(el('span', 'orv-confirmed', '✓ Potvrzeno'));
    } else if (!photo.potvrdit && existing) {
      existing.remove();
    }
  }
  function fillSelect(select, rootEl, templateSel, placeholder, value) {
    select.append(optionEl('', placeholder));
    const template = rootEl.querySelector(templateSel);
    const options = template && template.querySelectorAll ? Array.from(template.querySelectorAll('option')) : [];
    options.forEach(option => {
      if (!option.value) return;
      select.append(optionEl(option.value, option.textContent));
    });
    select.value = value || '';
  }
  function assignmentCard(ctx, photo) {
    const result = photo.result || {};
    const {card, body} = cardShell(photo, 'assign', needsConfirm(photo) ? 'duplicate' : 'assign');
    body.append(cardHead(photo, {}));
    const facts = factsNode(result, true);
    if (facts) body.append(facts);
    if (result.provozovatel) {
      body.append(el('p', 'orv-owner', 'Provozovatel: ' + result.provozovatel));
    }
    if (result.zprava) body.append(el('p', 'orv-message', result.zprava));
    const duplicate = duplicateBlock(ctx, photo);
    if (duplicate) body.append(duplicate);
    const defaults = batchDefaults(ctx.rootEl);
    const fields = el('div', 'orv-card-fields');
    const name = carName(result);
    const firma = el('select', 'orv-card-firma');
    firma.setAttribute('aria-label', 'Firma pro ' + name);
    fillSelect(firma, ctx.rootEl, '#orv-batch-firma', '— vyber firmu —',
      effective(photo, defaults).firma_id);
    firma.addEventListener('change', () => {
      photo.firmaOverride = firma.value || null;
      refreshPrices(ctx.rootEl, ctx.photos);
    });
    const typ = el('select', 'orv-card-typ');
    typ.setAttribute('aria-label', 'Typ úkonu pro ' + name);
    fillSelect(typ, ctx.rootEl, '#orv-batch-typ', '— vyber typ —',
      effective(photo, defaults).typ_kod);
    typ.addEventListener('change', () => {
      photo.typOverride = typ.value || null;
      refreshPrices(ctx.rootEl, ctx.photos);
    });
    const note = el('input', 'orv-card-poznamka');
    note.type = 'text';
    note.maxLength = MAX_NOTE;
    note.value = photo.poznamka || '';
    note.placeholder = 'Poznámka k úkonu (nepovinná, max. 120)';
    note.setAttribute('aria-label', 'Poznámka k úkonu ' + name);
    note.addEventListener('input', () => { photo.poznamka = note.value; });
    field(fields, 'Firma', firma);
    field(fields, 'Typ', typ);
    field(fields, 'Poznámka', note).classList.add('orv-card-field--wide');
    body.append(fields);
    body.append(el('p', 'orv-card-price',
      priceLabel(ctx.ceny, effective(photo, defaults))));
    return card;
  }
  function issueCard(ctx, photo) {
    const result = photo.result || {};
    const state = stateOf(photo) || 'chyba';
    const {card, body} = cardShell(photo, 'issue', state === 'necitelne' ? 'unreadable' : 'warn');
    body.append(cardHead(photo, {open: true}));
    const facts = factsNode(result, true);
    if (facts) body.append(facts);
    if (result.provozovatel) {
      body.append(el('p', 'orv-owner', 'Provozovatel: ' + result.provozovatel));
    }
    if (state === 'konflikt' && result.konflikt) {
      const conflict = result.konflikt;
      body.append(el('div', 'orv-conflict-label', FIELD_LABELS[conflict.pole] || 'Hodnota'),
        el('div', 'orv-conflict', 'V evidenci: ' + (conflict.evidence || '—') +
          ' · Na fotce: ' + (conflict.foto || '—')));
    }
    const before = earlier(result);
    if (before) body.append(el('p', 'orv-earlier', before));
    if (result.zprava) body.append(el('p', 'orv-message', result.zprava));
    const duplicate = duplicateBlock(ctx, photo);
    if (duplicate) body.append(duplicate);
    const candidates = kandidati(result);
    if (candidates.length) body.append(kandidatiNode(ctx, candidates));
    const actions = el('div', 'orv-card-actions');
    // A new photo is the fix for "nothing readable"; "Přečíst znovu" (same
    // photo) only helps a transient error, never an unreadable document.
    if (photo.blob && (state === 'necitelne' || state === 'chyba' || state === 'nenalezeno')) {
      const retake = el('button', 'btn btn-primary orv-retake-btn', 'Vyfotit znovu');
      retake.type = 'button';
      retake.addEventListener('click', () => ctx.actions.onRetake && ctx.actions.onRetake(photo));
      actions.append(retake);
    }
    if (photo.blob && state === 'chyba') {
      const retry = el('button', 'btn orv-retry-btn', 'Přečíst znovu');
      retry.type = 'button';
      retry.addEventListener('click', () => ctx.actions.onRetry && ctx.actions.onRetry(photo));
      actions.append(retry);
    }
    if (actions.children.length) body.append(actions);
    return card;
  }
  function writtenCard(ctx, photo) {
    const result = photo.result || {};
    const state = stateOf(photo);
    const {card, body} = cardShell(photo, 'written',
      state === 'zalozeno' ? 'created' : state === 'doplneno' ? 'filled' : 'same');
    body.append(cardHead(photo, {}));
    const facts = factsNode(result, false);
    if (facts) body.append(facts);
    const ukon = result.ukon || {};
    const written = [ukon.firma, ukon.typ, ukon.celkem != null ? kc(ukon.celkem) : ''].filter(Boolean);
    const note = noteValue(ukon.poznamka || photo.poznamka);
    const line = el('p', 'orv-written-line',
      (ukon.id ? 'Zapsáno do úkonu #' + ukon.id : 'Zapsáno') +
      (written.length ? ' · ' + written.join(' · ') : '') +
      (note ? ' · poznámka: ' + note : ''));
    body.append(line);
    const changes = valuesFor(result);
    changes.forEach(change => body.append(change));
    if (!changes.length && state === 'uz_doplneno') {
      const fields = [['rz', result.rz], ['orv', result.orv_cislo]].filter(x => x[1]);
      fields.forEach(([key, value]) => body.append(detailLine(FIELD_LABELS[key], value, value)));
    }
    if (ukon.id) {
      const open = el('button', 'btn orv-open-ukon orv-open-written', 'Otevřít a upravit úkon');
      open.type = 'button';
      open.dataset.ukon = String(ukon.id);
      body.append(open);
    }
    return card;
  }

  function render(rootEl, photos, actions) {
    actions = actions || {};
    const ceny = cenyOf(rootEl);
    const review = reviewPhotos(photos);
    const written = writtenPhotos(photos);
    const assignables = review.filter(assignable);
    // The firm on the ORV is only pre-selected; the person still confirms it.
    assignables.forEach(photo => {
      const navrh = photo.result && photo.result.navrh_firma_id;
      if (photo.firmaOverride === undefined && navrh) photo.firmaOverride = String(navrh);
    });
    // The shared firma+typ bar is only worth asking for 2+ cars (David:
    // "ptá se na firmu dvakrát i u jednoho auta").
    const bar = rootEl.querySelector('#orv-batch');
    const showBar = assignables.length >= 2;
    if (bar) {
      // When the bar disappears (cars got created), keep the shared choice on
      // the remaining cards instead of silently dropping it.
      if (!showBar && !bar.hidden) {
        const shared = batchDefaults(rootEl);
        assignables.forEach(photo => {
          if (photo.firmaOverride == null && shared.firma_id) photo.firmaOverride = shared.firma_id;
          if (photo.typOverride == null && shared.typ_kod) photo.typOverride = shared.typ_kod;
        });
      }
      bar.hidden = !showBar;
    }
    const summary = rootEl.querySelector('#orv-summary');
    if (summary) summary.hidden = false;
    const banner = bannerState(photos);
    const title = rootEl.querySelector('#orv-summary-title');
    if (title) {
      title.textContent = (banner.tone === 'warn' ? '⚠ ' : '✓ ') + banner.text;
      title.dataset.tone = banner.tone;
    }
    const counts = rootEl.querySelector('#orv-counts');
    if (counts) {
      counts.replaceChildren();
      const t = totals(photos);
      [[t.zalozeno, '✚ Založeno'], [t.doplneno, '✎ Doplněno'],
        [t.uz_doplneno, '✓ Beze změny'], [t.review, '⚠ Ke kontrole'],
        [t.necitelne, '✗ Nečitelné']].forEach(([n, label]) => {
        counts.append(el('span', 'orv-count-chip', label + ' · ' + n));
      });
    }
    const reviewSection = rootEl.querySelector('#orv-review');
    if (reviewSection) reviewSection.hidden = !review.length;
    const writtenSection = rootEl.querySelector('#orv-written');
    if (writtenSection) writtenSection.hidden = !written.length;
    const writtenTitle = rootEl.querySelector('#orv-written-title');
    if (writtenTitle) writtenTitle.textContent = 'Zapsáno';
    const rows = rootEl.querySelector('#orv-unassigned');
    const issues = rootEl.querySelector('#orv-issues');
    if (rows) rows.replaceChildren();
    if (issues) issues.replaceChildren();
    const ctx = {rootEl, photos, actions, ceny, showBar};
    review.forEach(photo => {
      const holder = assignable(photo) ? rows : issues;
      if (!holder) return;
      holder.append(assignable(photo) ? assignmentCard(ctx, photo) : issueCard(ctx, photo));
    });
    const results = rootEl.querySelector('#orv-results');
    if (results) {
      results.replaceChildren();
      written.forEach(photo => results.append(writtenCard(ctx, photo)));
    }
    updateCreateCount(rootEl, photos);
    return {review: review.length, written: written.length};
  }

  const api = {LABELS, PAY_LABELS, MAX_NOTE, stateOf, isWritten, needsAction, assignable,
    reviewPhotos, writtenPhotos, group, bannerState, totals, czechCars, czechJobs,
    dateCs, readFactsList, factText, earlier, kc, priceFor, priceLabel, cenyOf,
    existingList, visibleExisting, needsConfirm, existingLine, kandidati, batchDefaults, effective,
    noteValue, canCreate, selected, payload, applyCreateResults, updateCreateCount,
    refreshPrices, render};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OrvReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
