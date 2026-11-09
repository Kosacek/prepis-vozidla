/* Techničák report: what the scan read, what it wrote (and where), and the
   one-off decisions a person still has to make (2.7.2, 2026-11-05).

   The cards follow the /ukony rows David likes: small photo in the TOP-RIGHT
   (text stays left-aligned), one clear hierarchy — status chip, RZ + type tag,
   ORV chip, firm line with a colour dot, muted VIN/notes line, small actions.
   On the cards for a new car the price moved next to the note (it read as if it
   belonged to the RZ line); written cards keep it on the RZ line like /ukony.
   Every car carries its own firma + typ + poznámka; there is NO shared "apply
   to all" bar (David never assigns one firm to many cars at once).

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
  // Souhrn nahoře: jen štítky, které něco znamenají (David: „Založeno 0“ je
  // šum). Pořadí drží to, co je pro člověka nejdřív — co se zapsalo, pak co
  // ještě zbývá.
  const SUMMARY = [
    ['zalozeno', '✚ Založeno'],
    ['doplneno', '✎ Doplněno'],
    ['uz_doplneno', '✓ Beze změny'],
    ['review', '⚠ Ke kontrole'],
    ['necitelne', '✗ Nečitelné'],
  ];

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
  // Only non-zero chips, in the fixed order above. Everything zero → no chips
  // at all (the banner still names the state of the batch).
  function summaryChips(photos) {
    const t = totals(photos);
    return SUMMARY.filter(([key]) => t[key] > 0)
      .map(([key, label]) => ({key, n: t[key], text: label + ' · ' + t[key]}));
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
    return 'Dříve ' + [date, p.firma_zkratka || p.firma, p.typ].filter(Boolean).join(' · ');
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

  // -- #orv-data JSON (prices + firm colours) ----------------------------
  // Normalised firm map: id → {id, nazev, zkratka, color}. Accepts the array
  // the current backend sends and, defensively, an older id-keyed object.
  function firmsMap(data) {
    const out = {};
    const list = data && data.firmy;
    if (Array.isArray(list)) {
      list.forEach(f => {
        if (!f || f.id == null) return;
        out[String(f.id)] = {id: f.id, nazev: f.nazev || '',
          zkratka: f.zkratka || f.nazev || '', color: f.color || ''};
      });
    } else if (list && typeof list === 'object') {
      Object.keys(list).forEach(id => {
        const f = list[id] || {};
        out[String(id)] = {id, nazev: f.nazev || '',
          zkratka: f.zkratka || f.nazev || '', color: f.color || ''};
      });
    }
    return out;
  }
  function dataOf(rootEl) {
    const node = rootEl && rootEl.querySelector('#orv-data');
    if (!node) return {ceny: {}, firmy: {}};
    try {
      const data = JSON.parse(node.textContent || '{}');
      return {ceny: (data && data.ceny) || {}, firmy: firmsMap(data)};
    } catch (_) { return {ceny: {}, firmy: {}}; }
  }
  function cenyOf(rootEl) { return dataOf(rootEl).ceny; }
  function firmsOf(rootEl) { return dataOf(rootEl).firmy; }
  // Firm identity for one úkon view: id → colour map first, then the payload's
  // own zkratka/firma (older backend without firma_id must still render).
  function firmOf(view, firms) {
    const v = view || {};
    let info = v.firma_id != null ? (firms || {})[String(v.firma_id)] : null;
    if (!info && v.firma && firms) {
      const wanted = String(v.firma);
      Object.keys(firms).some(id => {
        const f = firms[id];
        if (f && (f.zkratka === wanted || f.nazev === wanted)) { info = f; return true; }
        return false;
      });
    }
    const zkratka = v.firma_zkratka || (info && info.zkratka) || v.firma || '';
    const color = (info && info.color) || '';
    return {zkratka: zkratka || '—', color: color || 'var(--muted)'};
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
    return ['#' + view.id, dateCs(view.datum), view.typ, view.firma_zkratka || view.firma,
      PAY_LABELS[view.stav_platby] || ''].filter(Boolean).join(' · ');
  }

  // -- Selection & payload ----------------------------------------------
  // Each photo carries its own choice; nothing is inherited from elsewhere.
  function choiceOf(photo) {
    return {firma_id: (photo && photo.firmaOverride) || '',
      typ_kod: (photo && photo.typOverride) || ''};
  }
  function noteValue(value) {
    return String(value == null ? '' : value).trim().slice(0, MAX_NOTE);
  }
  function canCreate(photo) {
    const chosen = choiceOf(photo);
    if (!assignable(photo) || !chosen.firma_id || !chosen.typ_kod) return false;
    // A car that is already in evidence needs an explicit "přesto založit".
    return !needsConfirm(photo) || !!photo.potvrdit;
  }
  function selected(photos) {
    return photos.filter(canCreate).map(photo => {
      const chosen = choiceOf(photo);
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
    const count = selected(photos).length;
    const button = rootEl && rootEl.querySelector('#orv-create-unmatched');
    if (!button) return count;
    button.textContent = 'Založit ' + count + ' ' + czechJobs(count);
    button.disabled = count === 0;
    button.hidden = !photos.some(assignable);
    return count;
  }
  // Live price + the type tag + button count after a card field changed.
  function refreshPrices(rootEl, photos) {
    const ceny = cenyOf(rootEl);
    photos.forEach(photo => {
      if (!assignable(photo) || !photo.cardEl) return;
      const chosen = choiceOf(photo);
      const price = photo.cardEl.querySelector('.orv-card-price');
      if (price) fillPrice(price, priceFor(ceny, chosen.firma_id, chosen.typ_kod), true);
      // The type tag appears only once a type is chosen (and disappears again
      // when the choice is cleared).
      const idRow = photo.cardEl.querySelector('.orv-card-id');
      const tag = idRow && idRow.querySelector('.orv-typ');
      if (chosen.typ_kod) {
        if (tag) tag.textContent = chosen.typ_kod;
        else if (idRow) idRow.append(el('span', 'tag orv-typ', chosen.typ_kod));
      } else if (tag) {
        tag.remove();
      }
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
  function field(container, labelText, control, extraCls) {
    const wrap = el('label', 'orv-card-field' + (extraCls ? ' ' + extraCls : ''));
    wrap.append(el('span', 'orv-card-label', labelText), control);
    container.append(wrap);
    return wrap;
  }
  function carName(result) {
    return (result && (result.rz || result.vin)) || 'bez RZ i VIN';
  }
  function metaNode(items) {
    const clean = (items || []).filter(Boolean);
    if (!clean.length) return null;
    const line = el('p', 'orv-meta');
    clean.forEach(text => line.append(el('span', 'orv-meta-item', text)));
    return line;
  }
  function vinItem(result) {
    if (!result || !result.vin) return null;
    return 'VIN ' + result.vin + (result.vin_zdroj ? ' · ' + vinSourceLabel(result.vin_zdroj) : '');
  }
  function detailLine(label, before, after) {
    const line = el('div', 'orv-change');
    line.append(el('strong', '', label), el('span', 'orv-change-before', before || '—'),
      el('span', 'orv-change-arrow', '→'), el('span', 'orv-change-after', after || '—'));
    return line;
  }
  // Only fields that really changed; "Beze změny" cards show no change rows at
  // all (repeating identical values was half the clutter David complained about).
  function changesNode(result) {
    const changes = (result && result.zmeny) || {};
    const rows = ['rz', 'orv', 'vin'].filter(k => changes[k] && changes[k].pred !== changes[k].po)
      .map(k => detailLine(FIELD_LABELS[k], changes[k].pred, changes[k].po));
    if (!rows.length) return null;
    const box = el('div', 'orv-changes');
    rows.forEach(row => box.append(row));
    return box;
  }
  function priceText(value) { return value == null ? '—' : kc(value); }
  function fillPrice(node, value, withLabel) {
    node.replaceChildren();
    if (withLabel) node.append(el('span', 'orv-card-price-k', 'Cena'));
    node.append(el('b', '', ' ' + priceText(value)));
    return node;
  }
  function priceNode(value, withLabel) { return fillPrice(el('span', 'orv-card-price'), value, withLabel); }
  // Row 2 of an assignment card: the note (wide, left) and the price (right).
  // David 2026-11-05: the price at the RZ line was confusing — it belongs next
  // to the note. The node keeps .orv-card-price, so refreshPrices() finds it.
  function noteRow(ceny, chosen, note) {
    const row = el('div', 'orv-card-noterow');
    field(row, 'Poznámka', note);
    row.append(priceNode(priceFor(ceny, chosen.firma_id, chosen.typ_kod), true));
    return row;
  }
  function statusChips(photo) {
    const result = photo.result || {};
    const state = stateOf(photo);
    const chips = el('span', 'orv-chips');
    const overwritten = state === 'doplneno' && (result.prepsano || []).length;
    chips.append(el('span', 'orv-status', overwritten ? 'Přepsáno' : LABELS[state] || 'Ke kontrole'));
    if (photo.upraveno) chips.append(el('span', 'orv-edited', '✓ Upraveno'));
    if (photo.potvrdit && needsConfirm(photo)) {
      chips.append(el('span', 'orv-confirmed', '✓ Potvrzeno'));
    }
    return chips;
  }
  function cardTop(photo) {
    const top = el('div', 'orv-card-top');
    top.append(statusChips(photo));
    return top;
  }
  // RZ + type tag (+ price only on written cards, where it matches /ukony).
  function idRow(result, typ, price) {
    const row = el('div', 'orv-card-id');
    row.append(el('b', 'orv-rz', (result && result.rz) || '—'));
    if (typ) row.append(el('span', 'tag orv-typ', typ));
    if (price) row.append(price);
    return row;
  }
  // The ORV number is the main thing the scan adds/changes — it gets its own
  // chip; an unread number is the red flag that caused the duplicate.
  function orvRow(result) {
    const orv = result && result.orv_cislo;
    const row = el('div', 'orv-card-orv');
    const chip = el('span', orv ? 'orv-orv' : 'orv-orv orv-orv--missing');
    chip.append(el('span', 'orv-orv-k', 'ORV'));
    chip.append(el('b', '', ' ' + (orv || 'nepřečteno')));
    row.append(chip);
    return row;
  }
  function firmNode(view, firms) {
    const identity = firmOf(view, firms);
    const line = el('div', 'orv-firm');
    const dot = el('span', 'firma-dot');
    dot.setAttribute('style', 'background:' + identity.color + ';');
    line.append(dot, el('span', 'orv-firm-name', identity.zkratka));
    return line;
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
    // Body first, photo second: the text column stays left-aligned and the
    // photo sits in the fixed right column (top-right of the card).
    card.append(body, preview);
    photo.cardEl = card;
    return {card, body};
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
    // Bold warning only — David: the explanatory paragraph is noise.
    box.append(el('p', 'orv-duplicate-title', '⚠ Tohle auto už v evidenci je'));
    const list = el('ul', 'orv-existing');
    items.forEach(view => {
      const item = el('li', 'orv-existing-item');
      item.append(el('span', 'orv-existing-line', existingLine(view)));
      const meta = [view.celkem != null ? kc(view.celkem) : '',
        view.poznamka ? 'Poznámka: ' + view.poznamka : ''].filter(Boolean).join(' · ');
      if (meta) item.append(el('span', 'orv-existing-meta', meta));
      const open = el('button', 'btn orv-open-existing', 'Otevřít existující úkon');
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
    const top = photo.cardEl && photo.cardEl.querySelector('.orv-card-top');
    if (!top) return;
    const existing = top.querySelector('.orv-confirmed');
    if (photo.potvrdit && !existing) {
      const chips = top.querySelector('.orv-chips');
      if (chips) chips.append(el('span', 'orv-confirmed', '✓ Potvrzeno'));
    } else if (!photo.potvrdit && existing) {
      existing.remove();
    }
  }
  function fillSelect(select, rootEl, sourceSel, placeholder, value) {
    select.append(optionEl('', placeholder));
    const source = rootEl && rootEl.querySelector(sourceSel);
    const options = source && source.querySelectorAll ? Array.from(source.querySelectorAll('option')) : [];
    options.forEach(option => {
      if (!option.value) return;
      const copy = optionEl(option.value, option.textContent);
      // Colours come from the hidden bank (`firma_colors` in the fragment); the
      // shared FirmaPick reads them from option.dataset.color.
      if (option.dataset && option.dataset.color) copy.dataset.color = option.dataset.color;
      select.append(copy);
    });
    select.value = value || '';
  }
  // Shared coloured firm picker (static/js/firma_pick.js, loaded before this
  // file). Without it (older page, JS off) the native <select> keeps working —
  // exactly like the Úkony form; never throw over a missing module.
  function attachFirmaPick(select) {
    const api = root.FirmaPick;
    if (!api || typeof api.attach !== 'function') return false;
    try {
      api.attach(select);
      return true;
    } catch (_) {
      return false;
    }
  }
  function assignmentCard(ctx, photo) {
    const result = photo.result || {};
    const {card, body} = cardShell(photo, 'assign', needsConfirm(photo) ? 'duplicate' : 'assign');
    const chosen = choiceOf(photo);
    body.append(cardTop(photo));
    // The price is NOT on the RZ line here (David: it read like part of the
    // plate); it goes down to the note row.
    body.append(idRow(result, chosen.typ_kod || null));
    body.append(orvRow(result));
    const duplicate = duplicateBlock(ctx, photo);
    if (duplicate) body.append(duplicate);
    const fields = el('div', 'orv-card-fields');
    const name = carName(result);
    const firma = el('select', 'orv-card-firma');
    firma.setAttribute('aria-label', 'Firma pro ' + name);
    fillSelect(firma, ctx.rootEl, '#orv-firma-options', '— vyber firmu —', chosen.firma_id);
    firma.addEventListener('change', () => {
      photo.firmaOverride = firma.value || null;
      refreshPrices(ctx.rootEl, ctx.photos);
    });
    const typ = el('select', 'orv-card-typ');
    typ.setAttribute('aria-label', 'Typ úkonu pro ' + name);
    fillSelect(typ, ctx.rootEl, '#orv-typ-options', '— vyber typ —', chosen.typ_kod);
    typ.addEventListener('change', () => {
      photo.typOverride = typ.value || null;
      refreshPrices(ctx.rootEl, ctx.photos);
    });
    const note = el('input', 'orv-card-poznamka');
    note.type = 'text';
    note.maxLength = MAX_NOTE;
    note.value = photo.poznamka || '';
    note.placeholder = 'Poznámka';
    note.setAttribute('aria-label', 'Poznámka k úkonu ' + name);
    note.addEventListener('input', () => { photo.poznamka = note.value; });
    field(fields, 'Firma', firma);
    field(fields, 'Typ', typ);
    body.append(fields);
    // Row 2: Poznámka (left, wide) + Cena (right).
    body.append(noteRow(ctx.ceny, chosen, note));
    const meta = metaNode([vinItem(result),
      result.provozovatel ? 'Provozovatel: ' + result.provozovatel : null]);
    if (meta) body.append(meta);
    // Options are filled and the select is in the card → the shared coloured
    // picker can wrap it. Without firma_pick.js the native select stays.
    attachFirmaPick(firma);
    return card;
  }
  function issueCard(ctx, photo) {
    const result = photo.result || {};
    const state = stateOf(photo) || 'chyba';
    const {card, body} = cardShell(photo, 'issue', state === 'necitelne' ? 'unreadable' : 'warn');
    const ukon = result.ukon;
    body.append(cardTop(photo));
    body.append(idRow(result, ukon && ukon.typ));
    body.append(orvRow(result));
    if (ukon && (ukon.firma_id != null || ukon.firma || ukon.firma_zkratka)) {
      body.append(firmNode(ukon, ctx.firms));
    }
    const duplicate = duplicateBlock(ctx, photo);
    if (duplicate) body.append(duplicate);
    if (state === 'konflikt' && result.konflikt) {
      const conflict = result.konflikt;
      const box = el('div', 'orv-conflict');
      box.append(el('b', 'orv-conflict-label', FIELD_LABELS[conflict.pole] || 'Hodnota'),
        el('span', '', ' V evidenci: ' + (conflict.evidence || '—') +
          (conflict.ponechano ? ' (ponecháno)' : '') +
          ' · Na fotce: ' + (conflict.foto || '—')));
      body.append(box);
      // The plate was kept, but the new ORV may still have been written.
      const written = changesNode(result);
      if (written) body.append(written);
    }
    const meta = metaNode([vinItem(result), earlier(result),
      result.provozovatel ? 'Provozovatel: ' + result.provozovatel : null]);
    if (meta) body.append(meta);
    const candidates = kandidati(result);
    if (candidates.length) body.append(kandidatiNode(ctx, candidates));
    // Konflikt má vlastní blok, duplicitu vysvětluje její nadpis a seznam
    // úkonů, u více shod řekne vše nadpis kandidátů — zpráva by se opakovala.
    if (!duplicate && !candidates.length && !(state === 'konflikt' && result.konflikt) &&
        result.zprava) {
      body.append(el('p', 'orv-message', result.zprava));
    }
    const actions = el('div', 'orv-card-actions');
    // Konflikt often already matched one úkon — keep the direct way in.
    if (ukon && ukon.id) {
      const open = el('button', 'btn orv-open-ukon orv-open-issue', 'Otevřít úkon');
      open.type = 'button';
      open.dataset.ukon = String(ukon.id);
      actions.append(open);
    }
    // A new photo is the fix for "nothing readable"; "Přečíst znovu" (same
    // photo) only helps a transient error, never an unreadable document.
    if (photo.blob && (state === 'necitelne' || state === 'chyba' || state === 'nenalezeno')) {
      const retake = el('button', 'btn orv-retake-btn', 'Vyfotit znovu');
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
    const ukon = result.ukon || {};
    const {card, body} = cardShell(photo, 'written',
      state === 'zalozeno' ? 'created' : state === 'doplneno' ? 'filled' : 'same');
    const price = ukon.celkem != null && isFinite(Number(ukon.celkem)) ? Number(ukon.celkem) : null;
    body.append(cardTop(photo));
    body.append(idRow(result, ukon.typ || null, price == null ? null : priceNode(price, false)));
    body.append(orvRow(result));
    body.append(firmNode(ukon, ctx.firms));
    const note = noteValue(ukon.poznamka || photo.poznamka);
    const meta = metaNode([vinItem(result), ukon.id ? 'Úkon #' + ukon.id : null,
      note ? 'Poznámka: ' + note : null]);
    if (meta) body.append(meta);
    if (state === 'doplneno') {
      const changes = changesNode(result);
      if (changes) body.append(changes);
    }
    if (ukon.id) {
      const actions = el('div', 'orv-card-actions');
      const open = el('button', 'btn btn-primary orv-open-written', 'Otevřít a upravit úkon');
      open.type = 'button';
      open.dataset.ukon = String(ukon.id);
      actions.append(open);
      body.append(actions);
    }
    return card;
  }

  function render(rootEl, photos, actions) {
    actions = actions || {};
    const data = dataOf(rootEl);
    const review = reviewPhotos(photos);
    const written = writtenPhotos(photos);
    // The firm on the ORV is only pre-selected; the person still confirms it.
    review.filter(assignable).forEach(photo => {
      const navrh = photo.result && photo.result.navrh_firma_id;
      if (photo.firmaOverride === undefined && navrh) photo.firmaOverride = String(navrh);
    });
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
      const chips = summaryChips(photos);
      chips.forEach(chip => counts.append(el('span', 'orv-count-chip', chip.text)));
      counts.hidden = !chips.length;
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
    const ctx = {rootEl, photos, actions, ceny: data.ceny, firms: data.firmy};
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

  const api = {LABELS, PAY_LABELS, FIELD_LABELS, MAX_NOTE, stateOf, isWritten, needsAction,
    assignable, reviewPhotos, writtenPhotos, group, bannerState, totals, summaryChips,
    czechCars, czechJobs, dateCs, readFactsList, factText, earlier, kc, priceFor, priceLabel,
    firmsMap, dataOf, cenyOf, firmsOf, firmOf, existingList, visibleExisting, needsConfirm,
    existingLine, kandidati, choiceOf, noteValue, canCreate, selected, payload,
    applyCreateResults, updateCreateCount, refreshPrices, render};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OrvReport = api;
})(typeof window !== 'undefined' ? window : globalThis);
