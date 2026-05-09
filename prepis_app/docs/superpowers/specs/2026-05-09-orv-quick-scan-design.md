# ORV Quick Scan — Design Spec

**Date:** 2026-05-09
**Status:** Draft
**Scope:** Reduce the camera-to-form workflow on Step 1 from 3+ clicks to a single keypress for the common ORV-only case.

## Problem

The current camera flow on Step 1 ("Naskenovat dokumenty") requires:

1. Click `📷 Kamera` → opens camera preview
2. Click `📸 Vyfotit` → captures photo, saves to disk, adds to batch
3. Click `🔍 Skenovat vše` → POSTs all batch images to `/api/scan-all`, applies result, stays on Step 1

The user (autobazar worker, 5–20 transfers/day) almost always scans only the ORV — COC and other docs are typed manually. The 3-click + manual-advance workflow burns time on the most repeated motion of their day.

## Goals

- Single keypress = capture + scan + navigate forward, when only an ORV is needed.
- Camera is open and ready by the time the user lands on Step 1, no preliminary click.
- Existing batch flow remains intact for the rare COC / multi-doc cases.
- ORV scan correctly fills the owner section in **all three modes** (prevod, zmena, zapis), not only prevod.

## Out of Scope

- Removing the existing `📸 Vyfotit` + `🔍 Skenovat vše` batch buttons. They stay.
- Touching `selectMode()` auto-advance. Keep current behavior — clicking a non-default mode card still auto-advances away from Step 1. The single-keypress flow targets the user's 95% case (default mode = `prevod`, which is preselected).
- Re-architecting `applyOrvData` beyond a 1-line mode branch. No new tests for frontend JS (no FE test harness exists).

## User Flow

1. User opens app → lands on Step 1 (Typ).
2. **First-ever visit:** browser shows camera-permission prompt. User approves. Camera preview opens automatically.
3. **Subsequent visits:** camera opens automatically (cached permission, gated behind one user gesture per page load — see "Camera auto-open" below).
4. User holds ORV under camera.
5. Presses **NumPad Enter** (or clicks the new `📸 Skenovat ORV` button).
6. Photo captured → POSTed to `/api/scan-orv` → response merged into form fields → `navNext()` advances wizard one step.
7. User lands on Step 4 (Vozidlo for `prevod`) or Step 3 (Nový for `zapis`) with VIN, RZ, Druh already filled. Owner data is filled into the appropriate section (Původní vlastník for prevod, Vlastník for zmena).

If the scan returns no usable data, do **not** advance — show the existing scan-result error inline and let the user retry.

## Design

### Camera auto-open

Add a `tryAutoOpenCamera()` call inside `activatePanel(1)` (the function that activates Step 1). It must be placed **before** the existing focus-first-input setTimeout (around line 811) so the camera permission prompt does not steal focus from the mode card. The call only fires if camera is currently closed (`!cameraStream`).

Browsers require a user gesture for `getUserMedia()` even with cached permission. Strategy:

- On first `activatePanel(1)` after page load, attempt `openCamera()` directly. If browser blocks (NotAllowedError or InvalidStateError), silently swallow and fall back to the existing manual `📷 Kamera` button.
- Add a one-shot `pointerdown` listener on `document.body` that calls `tryAutoOpenCamera()` once, then removes itself. This catches the case where the first attempt failed: the next time the user clicks anywhere on the page, camera attempts to open.

**Race-condition guard for mode-card clicks:** the pointerdown listener must skip when `e.target.closest('.mode-card')` is non-null. A click on any mode card triggers `selectMode()` → `setTimeout(() => navNext(), 150)` → `activatePanel(n !== 1)` → `closeCamera()`. Auto-opening the camera in that 150 ms window causes a visible flicker (camera light on then off, video frame appears then vanishes). Skipping mode-card targets avoids the flicker; the user gets camera-open behavior on any other first click (any button, any field, even page background).

This keeps the existing manual button as a guaranteed fallback while skipping the click in the common case.

### New "Skenovat ORV" button

Add a new button to the camera-action row (lines ~302-306 in `templates/index.html`), prominent, primary style:

```html
<button id="quick-scan-btn" onclick="quickScanOrv()" style="flex:1;padding:10px;background:var(--primary);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;">📸 Skenovat ORV</button>
```

Replaces the existing `📸 Vyfotit` button in visual prominence. The old `📸 Vyfotit` button is kept but moved to a less prominent position — same row, smaller padding, tertiary style — for users who want to add a photo to the batch without scanning yet.

### NumPad Enter keyboard shortcut

Bind a `keydown` listener on `document` that fires only:

- when `event.code === 'NumpadEnter'` (not `event.key === 'Enter'`, to avoid conflicting with mode-card / form-input Enter handlers);
- when the user is on Step 1 (`currentPanel() === 1` — function exists at line 671);
- when the camera is open (`cameraStream` is truthy);
- when no scan is currently in-flight (a new `_scanInFlight` boolean guards re-entrance);
- when the focused element is **not** a typing surface: `!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)`. Step 1 currently has no inputs, but this is cheap parity with existing keydown handlers and protects against future Step 1 inputs.

On match: call `quickScanOrv()`. Also `e.preventDefault()` to suppress any default Enter behavior.

### `quickScanOrv()` action

```js
let _scanInFlight = false;
async function quickScanOrv() {
  if (_scanInFlight) return;
  if (!cameraStream) { alert('Kamera není zapnutá.'); return; }

  _scanInFlight = true;
  const btn = document.getElementById('quick-scan-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Skenuji…'; }

  try {
    // Capture from current video frame
    const video = document.getElementById('camera-video');
    const canvas = document.getElementById('camera-canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.translate(canvas.width, canvas.height);
    ctx.rotate(Math.PI);
    ctx.drawImage(video, 0, 0);
    const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.92));

    // Scan
    const fd = new FormData();
    fd.append('image', blob, 'capture.jpg');
    fd.append('model', getModel());
    const resp = await fetch('/api/scan-orv', { method: 'POST', body: fd });
    const result = await resp.json();

    if (!result.success || !result.data) {
      alert('Sken selhal: ' + (result.error || 'žádná data'));
      return;
    }

    const filled = await applyOrvData(result.data);
    if (!filled.length) {
      alert('Z fotky se nepodařilo přečíst žádná data. Zkus to znovu.');
      return;
    }

    // Success → close camera, advance wizard
    closeCamera();
    navNext();
  } catch (e) {
    alert('Chyba při skenování: ' + e.message);
  } finally {
    _scanInFlight = false;
    if (btn) { btn.disabled = false; btn.textContent = '📸 Skenovat ORV'; }
  }
}
```

Endpoint choice: `/api/scan-orv` (single-image, ORV prompt, with rotate-180 retry). Already exists in `app.py` at line ~919.

### `applyOrvData` mode-aware owner prefix

Existing function (`templates/index.html` line ~1448) hardcodes `puvodni_` for owner fields. Replace ONLY the owner+provozovatel sections with a mode-aware prefix. The vehicle-data section at the bottom (lines ~1474-1495 — VIN, registracni_znacka, kategorie/typ/znacka/barva, cislo_schvaleni, osvedceni_orv lookup, druh select option matching) stays VERBATIM. Do not bulk-replace the whole function.

The full revised function (preserving the vehicle section verbatim from current code):

```js
async function applyOrvData(d) {
  let filled = [];
  const ownerPrefix = (appMode === 'prevod') ? 'puvodni' : 'novy';
  const v = d.vlastnik || {};
  if (setVal(`${ownerPrefix}_jmeno`,  v.jmeno))  filled.push('jméno vlastníka');
  if (setVal(`${ownerPrefix}_adresa`, v.adresa)) filled.push('adresa');
  setVal(`${ownerPrefix}_psc`,   v.psc);
  if (setVal(`${ownerPrefix}_rc_1`, v.rc_1)) filled.push('RČ');
  setVal(`${ownerPrefix}_rc_2`, v.rc_2);
  if (setVal(`${ownerPrefix}_ico`, v.ico)) filled.push('IČO');
  if (v.ico) { await matchFirmByIco(ownerPrefix, v.ico); }
  else if (v.jmeno) { const matched = await matchFirmByName(ownerPrefix, v.jmeno); if (matched) filled.push('IČO ze saved firem'); }

  const p = d.provozovatel || {};
  if (p.same_as_vlastnik === false && p.jmeno) {
    const cb = document.getElementById(`${ownerPrefix}_prov_jiny`);
    if (cb && !cb.checked) { cb.checked = true; toggleProvozovatel(ownerPrefix); }
    if (setVal(`${ownerPrefix}_prov_jmeno`,  p.jmeno))  filled.push('provozovatel');
    setVal(`${ownerPrefix}_prov_adresa`, p.adresa);
    setVal(`${ownerPrefix}_prov_psc`,    p.psc);
    setVal(`${ownerPrefix}_prov_rc_1`,   p.rc_1);
    setVal(`${ownerPrefix}_prov_rc_2`,   p.rc_2);
    setVal(`${ownerPrefix}_prov_ico`,    p.ico);
    if (p.ico) { await matchFirmByIco(`${ownerPrefix}_prov`, p.ico); }
    else if (p.jmeno) { await matchFirmByName(`${ownerPrefix}_prov`, p.jmeno); }
  }

  // === Vehicle section: KEEP VERBATIM from current code (lines 1474-1495) ===
  if (d.vin) {
    const vinId = appMode === 'prevod' ? 'vin' : 'vin_z';
    if (setVal(vinId, d.vin)) filled.push('VIN');
  }
  if (setVal('registracni_znacka', d.registracni_znacka)) filled.push('RZ');
  setVal('kategorie_vozidla', d.kategorie_vozidla);
  setVal('typ_vozidla',       d.typ_vozidla);
  if (setVal('znacka',        d.znacka))       filled.push('značka');
  if (setVal('barva_vozidla', d.barva_vozidla)) filled.push('barva');
  setVal('cislo_schvaleni',   d.cislo_schvaleni);
  if (d.osvedceni_serie || d.osvedceni_cislo) {
    setVal('osvedceni_orv', (d.osvedceni_serie || '') + (d.osvedceni_cislo || ''));
    _orvLast = '';
    lookupOrv();
  }
  if (d.druh_vozidla) {
    for (const selId of ['druh_vozidla', 'druh_vozidla_z']) {
      const sel = document.getElementById(selId);
      if (sel) for (let o of sel.options) { if (o.value.includes(d.druh_vozidla.toLowerCase().split(' ')[0])) { sel.value = o.value; break; } }
    }
    filled.push('druh');
  }
  return filled;
}
```

For modes `zapis` and `zmena`, owner data goes to `novy_*`. For `prevod`, it goes to `puvodni_*`. The vehicle-section VIN-id branch (`appMode === 'prevod' ? 'vin' : 'vin_z'`) preserves the existing behavior unchanged: prevod uses shared `vin`, zapis/zmena route through `vin_z` for zapis (zmena now shares `vin` but the existing line is untouched and `vin_z` setVal is a harmless no-op for zmena since the panel is hidden — leave it).

This changes behavior for `zapis` mode too, but only in the rare case where the user scans an ORV while in zapis flow (zapis = first registration, where ORV doesn't yet exist). Writing owner data to `novy_*` is exactly what zapis uses, so harmless.

### Existing batch flow

`📸 Vyfotit` (re-styled, less prominent) and `🔍 Skenovat vše` remain. Used when:

- User wants to scan a COC list
- User wants to scan multiple docs in one Claude Vision call (better cross-doc merge)

No code changes there.

### Closing the camera after scan

After successful scan and navigation, `closeCamera()` is called inside `quickScanOrv`. This stops the video stream so the camera light goes off (privacy + battery). When user navigates back to Step 1 (e.g., to switch mode), `tryAutoOpenCamera()` re-opens it.

## Error Handling

- `getUserMedia` fails → silent fallback to manual `📷 Kamera` button (already exists).
- Scan API non-200 / `success: false` → existing `alert()` pattern; do NOT call `navNext()`.
- Scan returned but no fields filled → `alert('Z fotky se nepodařilo přečíst žádná data')`; do NOT call `navNext()`.
- User spams NumPad Enter → `_scanInFlight` guard ignores subsequent presses while one is in flight.

## Frontend changes only

No backend changes. `/api/scan-orv` already exists and works. No version bump needed for backend, but the bundled `templates/index.html` change requires a rebuild of the PyInstaller exe and redeploy to NAS.

## Versioning + Deploy

- `VERSION` → `1.1.1` (patch — UX improvement, no API change)
- `version.py` → `1.1.1`
- `app.py __version__` → `1.1.1`
- Build via PyInstaller, deploy via existing PowerShell copy.

## Testing

No unit tests added (no FE test harness). Manual smoke test:

1. Start dev server `python app.py`
2. Open browser → permission prompt → grant
3. Hold a real ORV under camera
4. Press NumPad Enter
5. Verify: PDF capture happens, scan result appears, fields fill, wizard advances to Step 4 (Vozidlo) for prevod
6. Switch to mode = zmena → go back to Step 1 → press NumPad Enter again → verify owner data lands in `novy_*` fields (visible on the Vlastník panel after advancing)

## Risks & Open Questions

- **Camera light visible after scan.** `closeCamera()` is called explicitly; minimal risk.
- **Multiple `applyOrvData` calls overwriting each other.** Not relevant here (single-shot per press), but if user presses Enter twice in a row, the in-flight guard blocks the second. After the first completes and navigates away, the second can't fire because `currentPanel() !== 1`.
- **`event.code === 'NumpadEnter'` portability.** Standard since ~2017. All modern Chrome/Firefox/Safari support. Petr's PC is Windows 10+ with modern Chrome — no concern.
