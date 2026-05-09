# Změna technických údajů — Design Spec

**Date:** 2026-05-09
**Status:** Draft (rev. 2 — addresses architect review)
**Scope:** Add a third operating mode to the Přepis Vozidla Flask app for filling the Czech "Žádost o zápis změn údajů v registru silničních vozidel" form (Skl. č. 37).

## Problem

The app currently supports two modes:

- **prevod** — vehicle ownership transfer (generates `zmeny.pdf` + `zapis.pdf`)
- **zapis** — first-time vehicle registration (generates `zapis.pdf`)

The user (autobazar worker, Brno) also processes "změna technických údajů" requests — recording technical changes in the vehicle register (e.g. tow hitch installation, color change, A50-X entries). Today these are filled by hand. The new mode automates the process using the same UI flow and the same scanned-document data pipeline.

## Out of Scope

- Multi-line free text for "Žádá o provedení změny". The PDF reserves 5 lines (`fill_12..fill_16`); we render only the first and leave the rest blank. Single-line covers the practical use cases ("zápis A50-X", "zápis"). Extension is a one-line code change later if needed.
- Validation of change codes (e.g. "A50-X" format) — left as free text.
- Dynamic preset catalog — start with two fixed presets; extend later.
- Page 2 of the PDF ("Záznam registračního místa") — left blank, filled by the úřad clerk, just like page 3 of `zmeny.pdf`.

## User Flow

1. **Typ** — selects the new mode card "Změna technických údajů".
2. **Vozidlo** — fills VIN + RZ + Druh vozidla (can pre-fill via ORV scan, same as current modes).
3. **Vlastník** — fills owner data (jméno, RČ/IČO, adresa, PSČ) with optional "Jiný provozovatel" toggle that reveals a second party block. At the bottom of this panel: a new section **"Žádá o provedení změny"** with a single text input and two preset buttons (`zápis A50-X`, `zápis`) that fill the input.
4. **Generovat** — produces a single PDF `zmena_{timestamp}.pdf`, downloadable/printable from the same review screen.

## Design

### New mode card on Step 1

A third `<div class="mode-card" data-mode="zmena">` appears on the type-selection panel, with icon and Czech description. The existing `selectMode()` and Tab/Enter keyboard handling already iterates over all `.mode-card` elements, so no JS change is needed for selection.

### Reuse existing field state

The new mode reuses the form state already used by `zapis nového vozidla`:

- `novy_jmeno`, `novy_rc_1`, `novy_rc_2`, `novy_ico`, `novy_adresa`, `novy_psc`, `novy_id` — primary party (Vlastník)
- `novy_prov_jiny` (bool) → `novy_prov_jmeno`, `novy_prov_rc_1`, `novy_prov_rc_2`, `novy_prov_ico`, `novy_prov_adresa`, `novy_prov_psc`, `novy_prov_id` — secondary party (Provozovatel) when checked
- `vin`, `registracni_znacka`, `druh_vozidla` — vehicle identification

No new state is needed for the parties or vehicle. ORV/OP scan pre-fill works without change.

### New form field

Single new field on Step 3:

- `zadost_zmena` (string, free-text input, max 80 chars) — populates `fill_12` (first line of "Žádá o provedení změny") in the PDF.

### Wizard flow definition

Add to the `flows` object in `templates/index.html`:

```js
zmena: { panels: [1, 4, 3, 5], labels: ['Typ', 'Vozidlo', 'Vlastník', 'Generovat'] }
```

Identical shape to the `zapis` flow. The Vlastník panel (panel 3) gets a new sub-section at the bottom that is conditionally shown when `appMode === 'zmena'`.

### Pinned PDF field mapping (`zmena_udaju.pdf`)

Mapping confirmed by an empirical marker fill (one distinct value per field, rendered and read off the PDF). Documented here so implementation does not have to rediscover it.

| PDF field | Maps to | Notes |
|---|---|---|
| `comb_1` | `registracni_znacka` | comb, 7 chars |
| `comb_2` | `vin` | comb, 17 chars |
| `Druh vozidla` | `druh_vozidla` | text |
| `fill_2` | vlastník `novy_jmeno` (line 1) | text |
| `fill_3` | (vlastník jméno line 2 — leave blank, app uses single-line names) | text |
| `comb_3` | vlastník `novy_rc_1` (rodné číslo first half + slash + second half — uses 10-char comb so write `rc_1 + "/" + rc_2`) | comb |
| `comb_4` | vlastník `novy_ico` | comb, 8 chars |
| `Adresa místa pobytu... 1` | vlastník `novy_adresa` | text |
| `Adresa místa pobytu... 2` | (line 2, leave blank) | text |
| `fill_6` | vlastník `novy_psc` | text |
| `fill_7` | provozovatel `novy_prov_jmeno` (line 1) — **only if `novy_prov_jiny`** | text |
| `fill_8` | (line 2, leave blank) | text |
| `comb_5` | provozovatel `novy_prov_rc_1` + "/" + `novy_prov_rc_2` — only if jiný | comb |
| `comb_6` | provozovatel `novy_prov_ico` — only if jiný | comb |
| `Adresa místa pobytu... 1_2` | provozovatel `novy_prov_adresa` — only if jiný | text |
| `Adresa místa pobytu... 2_2` | (blank) | text |
| `fill_11` | provozovatel `novy_prov_psc` — only if jiný | text **(NOT žádá-o-změnu)** |
| `fill_12` | `zadost_zmena` (single user input) | text |
| `fill_13..fill_16` | (blank — additional lines for žádá-o-změnu, unused) | text |
| `V` | místo `Brně` | text (default) |
| `dne` | tomorrow's working date | text |

Page 2 fields (`undefined`, `fill_2_2`, `fill_3_2`, `fill_4`, `fill_5..fill_11_2`, `fill_12_a`, `fill_12_b`, `fill_12_2`, `fill_14_2`, `undefined_2`, `fill_16_2`, `fill_17`, `fill_18`, `Jiné doklady`, `V_2`, `dne_2`) are filled by the úřad clerk and left blank.

**Critical:** when `novy_prov_jiny == False`, the entire provozovatel block (`fill_7`, `fill_8`, `comb_5`, `comb_6`, `Adresa... 1_2`, `Adresa... 2_2`, `fill_11`) **must be left empty**. The form states "Vyplnit jen, když je provozovatel odlišný od vlastníka". Do not silently copy vlastník data into provozovatel as `build_zmeny_fields` does for the existing `zmeny.pdf` (which has different semantics).

### Backend changes (`app.py`)

1. Constant: `PDF_ZMENA = os.path.join(BASE_DIR, "pdfs", "zmena_udaju.pdf")`.
2. New helper `build_zmena_fields(data: dict) -> dict` next to existing `build_zmeny_fields` / `build_zapis_fields`. It:
   - Always populates vlastník fields from `novy_*` keys.
   - Populates provozovatel fields **only** when `data.get("novy_prov_jiny")` is truthy. Otherwise emits empty strings for those fields.
   - Combines `novy_rc_1` + "/" + `novy_rc_2` into a single `comb_3` value (and analogously for provozovatel `comb_5`).
   - Defaults `V` to `"Brně"` and `dne` to `_next_working_day()`.
3. New branch in `/api/generate`:
   ```python
   elif mode == "zmena":
       zmena_bytes = fill_pdf(PDF_ZMENA, build_zmena_fields(data))
       if zmena_overlays:
           zmena_bytes = add_id_overlay(zmena_bytes, zmena_overlays)
       fname = os.path.join(out_dir, f"zmena_{ts}.pdf")
       with open(fname, "wb") as f:
           f.write(zmena_bytes)
       result["zmena"] = f"/download/zmena_{ts}.pdf"
   ```
4. **Unknown-mode guard** at the top of `/api/generate`:
   ```python
   if mode not in {"prevod", "zapis", "zmena"}:
       return jsonify({"success": False, "error": f"Neznámý mód: {mode}"}), 400
   ```
   This prevents an old client (post-rollback or mid-rollout) hitting a pre-`zmena` server and silently producing a wrong-PDF; conversely a new client hitting an old server would already 500 on missing branch — explicit error is clearer.
5. **Startup field-name sanity check**: at module import time, load each of the three template PDFs, fetch their AcroForm field names, and warn (Python `logging.warning`) for any expected name that's missing. Implemented as a small helper called once at startup. Required field set per template lives in a constant dict near `PDF_ZMENA` so it stays close to the mapping.

### ID overlay

Use the existing `add_id_overlay()` helper. Overlays for `zmena` mode are page-0 only (single page filled). Y-coordinates were not yet measured during empirical fill; they are determined during implementation by visually placing markers on the rendered PDF and adjusting once. Approximate starting points based on the existing `zmena_udaju.pdf` layout:

- vlastník ID overlay: y ≈ 700 (just below the vlastník jméno fields)
- provozovatel ID overlay (only when jiný): y ≈ 555 (just below provozovatel jméno fields)

X-coordinate stays at 554 (right-align, same as existing modes). The `add_id_overlay()` function is page-size agnostic since it draws onto a fresh A4 canvas and merges; this PDF is A4 — confirmed by reading `mediabox` from the PDF (verify in implementation).

### Plné moci

Existing logic in `/api/generate` iterates `puvodni_ico, novy_ico, puvodni_prov_ico, novy_prov_ico` and attaches plné moci PDFs. For `zmena` mode, only `novy_ico` and `novy_prov_ico` (when jiný) are present, so the existing loop works without change.

### PyInstaller bundle

The `prepis_vozidla.spec` already lists `('pdfs', 'pdfs')` in `datas=`, which copies the entire `pdfs/` directory into the bundle. Adding `zmena_udaju.pdf` to that directory automatically ships it — no `.spec` change needed. Confirmed by reading the spec; the new build run produces `dist/PrepisVozidla/_internal/pdfs/zmena_udaju.pdf`.

## Frontend changes (`templates/index.html`)

### Step 1 — third mode-card

Add after the `zapis` card:

```html
<div class="mode-card" data-mode="zmena" onclick="selectMode(this)" tabindex="0" onkeydown="...">
  <div class="mode-icon">🔧</div>
  <div>
    <div class="mode-title">Změna technických údajů</div>
    <div class="mode-desc">Změny v registru (zápis A50-X, ...). Generuje zmena_udaju.pdf.</div>
  </div>
</div>
```

### Step 4 (Vozidlo panel) — third sub-block

Currently panel-4 contains two divs:

- `vozidlo-prevod-fields` — RZ + VIN + Druh + Číslo ORV + Jiný doklad + Typ žádosti radios
- `vozidlo-zapis-fields` — VIN_z + Druh_z + Kategorie + Typ + Značka + Barva + Poznámky

For `zmena` we need just RZ + VIN + Druh. Three approaches considered:

- (a) Add a third div `vozidlo-zmena-fields` with the three inputs.
- (b) Reuse `vozidlo-prevod-fields` and conditionally hide the ORV / "Jiný doklad" / "Typ žádosti radios" sub-sections when `appMode === 'zmena'`.
- (c) Refactor: extract a shared `vozidlo-rz-vin-druh` block referenced by both prevod and zmena.

**Decision: (a)** — third div with `id="registracni_znacka_zm"`, `id="vin_zm"`, `id="druh_vozidla_zm"`. Cleanest, no risk of accidentally including unrelated fields in payload, mirrors the existing two-div pattern. The existing payload-build code at line ~1220 then needs an `appMode === 'zmena'` branch to read from these IDs.

The visibility toggle in `activatePanel(4)` becomes:

```js
document.getElementById('vozidlo-prevod-fields').style.display = appMode === 'prevod' ? '' : 'none';
document.getElementById('vozidlo-zapis-fields').style.display  = appMode === 'zapis' ? '' : 'none';
document.getElementById('vozidlo-zmena-fields').style.display  = appMode === 'zmena' ? '' : 'none';
```

### Step 3 (Vlastník panel) — new sub-section

Add at the bottom of the panel, conditionally shown only when `appMode === 'zmena'`:

```html
<div id="zmena-changes-section" style="display:none;">
  <hr class="divider">
  <div class="section-label">Žádá o provedení změny</div>
  <div class="form-grid">
    <div class="field full">
      <input type="text" id="zadost_zmena" maxlength="80" placeholder="napr. zápis A50-X">
    </div>
  </div>
  <div style="display:flex;gap:8px;margin-top:8px;">
    <button type="button" class="preset-btn" onclick="document.getElementById('zadost_zmena').value='zápis A50-X'">zápis A50-X</button>
    <button type="button" class="preset-btn" onclick="document.getElementById('zadost_zmena').value='zápis'">zápis</button>
  </div>
</div>
```

`activatePanel(3)` (or wherever the panel becomes active) toggles `zmena-changes-section` visibility.

### Generate request and result rendering

Currently the result-handling code hardcodes `result.zmeny` → `btn-zmeny` and `result.zapis` → `btn-zapis`. We add `result.zmena` → `btn-zmena`:

1. Add `<a id="btn-zmena" class="btn-download" style="display:none;">Stáhnout zmena.pdf</a>` to the output-card.
2. Update the result handler (around line 1246) to:
   ```js
   generatedUrls = { zmeny: result.zmeny, zapis: result.zapis, zmena: result.zmena, plne_moce: result.plne_moce || [] };
   for (const [key, btnId] of [['zmeny','btn-zmeny'], ['zapis','btn-zapis'], ['zmena','btn-zmena']]) {
     const url = result[key];
     const btn = document.getElementById(btnId);
     if (url) { btn.href = url; btn.style.display = ''; } else { btn.style.display = 'none'; }
   }
   ```
3. Update `printAll()`:
   ```js
   ['zmeny','zapis','zmena'].forEach(k => { if (generatedUrls[k]) window.open(generatedUrls[k], '_blank'); });
   (generatedUrls.plne_moce || []).forEach(url => window.open(url, '_blank'));
   ```

### Generate request payload

Existing payload-build code reads `vin` / `vin_z` based on `appMode`. Extend to handle `zmena`:

```js
vin:                 appMode === 'prevod' ? v('vin') : (appMode === 'zapis' ? v('vin_z') : v('vin_zm')),
registracni_znacka:  appMode === 'prevod' ? v('registracni_znacka') : (appMode === 'zmena' ? v('registracni_znacka_zm') : ''),
druh_vozidla:        appMode === 'prevod' ? v('druh_vozidla') : (appMode === 'zapis' ? v('druh_vozidla_z') : v('druh_vozidla_zm')),
zadost_zmena:        appMode === 'zmena' ? v('zadost_zmena') : '',
```

### Summary screen

The shrnutí (review) screen already iterates known keys; add a row for `zadost_zmena` shown only when `appMode === 'zmena'`.

## Testing

The project has no existing test infrastructure. We add a minimal `tests/` directory with `pytest` and a `requirements-dev.txt` with `pytest`:

1. **`tests/test_build_zmena_fields.py`** — pure unit tests for the field-map builder:
   - With minimal vlastník data → vlastník fields populated, provozovatel fields all `""`.
   - With `novy_prov_jiny=True` and full provozovatel data → both blocks populated.
   - With `zadost_zmena="zápis A50-X"` → `fill_12 == "zápis A50-X"`, `fill_13..fill_16 == ""`.
   - With právnická osoba (IČO only, no RČ) → `comb_4` set, `comb_3` empty.
2. **`tests/test_pdf_render_zmena.py`** — golden-file integration test:
   - Builds fields with a fixed test vector.
   - Calls `fill_pdf(PDF_ZMENA, fields)` and reads back the resulting `/V` annotations.
   - Asserts each PDF field has the expected content. Acts as a regression guard against pypdf version drift, AcroForm-encoding bugs, or md.gov.cz silently shipping a renamed PDF (which would already break the startup sanity check).
3. **`tests/test_generate_route.py`** — Flask test client hits `/api/generate` with `mode=zmena` payload, asserts response shape (`success: True`, `zmena: "/download/zmena_*.pdf"`) and that the file exists on disk.

E2E (Playwright) is out of scope. No CI is set up; tests are runnable locally via `pytest`.

## Error Handling

- **Unknown mode** → 400 with Czech error message (see backend changes #4).
- **Missing required fields** → not validated server-side (consistent with current `prevod` / `zapis` behavior). The user reviews the PDF before printing.
- **PDF write error** → propagates as 500 (same as existing).
- **Future md.gov.cz drift** → startup sanity check logs `WARNING: Field 'X' missing from zmena_udaju.pdf`. The fill operation continues for other fields. The test suite's golden-file render will fail, surfacing the issue on next CI run / local pytest.

## Versioning + Deploy

Feature addition. Bump from `1.0.19` to `1.1.0`.

- `VERSION` → `1.1.0`
- `version.py` → `1.1.0`
- `app.py` `__version__` → `1.1.0`
- Build via `python -m PyInstaller prepis_vozidla.spec --noconfirm`
- Deploy via `deploy_to_nas.bat` (running app must be closed first — Petr or whoever has it open)
- Auto-updater handles the rest: running clients detect VERSION mismatch on NAS and prompt restart.

## Implementation Order

1. Backend: `PDF_ZMENA` constant + `build_zmena_fields` + `/api/generate` branch + unknown-mode guard + startup sanity check.
2. Backend tests: unit + golden-file render.
3. Frontend: third mode-card + flow + `vozidlo-zmena-fields` div + `zmena-changes-section` + payload + result rendering.
4. Manual smoke test in dev mode (`python app.py`): fill the form end-to-end, verify generated PDF visually.
5. ID overlay coordinate measurement + adjustment.
6. Version bump + build + deploy.

Each step verifiable independently. Steps 1 and 3 can be parallelized with mocked counterparts but linear order is fine for a single-developer pass.
