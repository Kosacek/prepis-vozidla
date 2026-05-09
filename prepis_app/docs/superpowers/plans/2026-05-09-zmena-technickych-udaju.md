# Změna technických údajů — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third operating mode "Změna technických údajů" to the Přepis Vozidla Flask app, generating filled `zmena_udaju.pdf` from a 4-step wizard that reuses existing owner/operator state.

**Architecture:** Extend the existing two-mode pattern (prevod, zapis) with a third `zmena` mode. Reuse `novy_*` and `novy_prov_*` form state from the `zapis` flow plus existing vehicle ID fields. Add one new field `zadost_zmena` for the change description. Backend gets a new `build_zmena_fields()` and a third branch in `/api/generate`. Frontend gets a third mode-card, a new vehicle sub-block, and a new section on the Vlastník panel.

**Tech Stack:** Python 3.x, Flask, pypdf (AcroForm fill), reportlab (overlay), vanilla HTML/JS, PyInstaller (packaging). Pytest for tests (newly added).

**Spec:** [`docs/superpowers/specs/2026-05-09-zmena-technickych-udaju-design.md`](../specs/2026-05-09-zmena-technickych-udaju-design.md)

---

## File Structure

**Created:**
- `pdfs/zmena_udaju.pdf` — official AcroForm template (already in place at start of plan, copied from user's source)
- `tests/__init__.py` — empty marker
- `tests/conftest.py` — pytest config + Flask test client fixture
- `tests/test_build_zmena_fields.py` — unit tests for the field-map builder
- `tests/test_pdf_render_zmena.py` — golden-file PDF render test
- `tests/test_generate_route_zmena.py` — Flask route integration test
- `requirements-dev.txt` — `pytest`, `pytest-flask` (or just `pytest`)

**Modified:**
- `app.py` — new constant `PDF_ZMENA`, new `build_zmena_fields()`, new branch in `/api/generate`, unknown-mode guard, startup field-name sanity check, ID overlay logic for zmena mode, version bump
- `templates/index.html` — third mode-card, new flow entry, `vozidlo-zmena-fields` div, `zmena-changes-section`, payload + result-rendering + summary updates
- `VERSION` — `1.0.19` → `1.1.0`
- `version.py` — `1.0.19` → `1.1.0`

**Untouched:** `prepis_vozidla.spec` (auto-bundles new PDF via existing `('pdfs','pdfs')`), `launcher.py`, `updater.py`.

---

## Task 1: Set up pytest infrastructure

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create dev requirements**

```
# requirements-dev.txt
pytest>=8.0
```

- [ ] **Step 2: Install dev deps**

Run: `pip install -r requirements-dev.txt`
Expected: pytest installed, no errors.

- [ ] **Step 3: Create empty `tests/__init__.py`**

Empty file (just touch it).

- [ ] **Step 4: Create `tests/conftest.py` with Flask client fixture**

```python
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

- [ ] **Step 5: Verify pytest discovers no tests yet**

Run: `pytest tests/ -v`
Expected: `no tests ran`, exit 5.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt tests/__init__.py tests/conftest.py
git commit -m "test: scaffold pytest infrastructure"
```

---

## Task 2: TDD — `build_zmena_fields` minimum (vlastník only, no jiný provozovatel)

**Files:**
- Create: `tests/test_build_zmena_fields.py`
- Modify: `app.py` (add `build_zmena_fields` near the other build_* helpers)

- [ ] **Step 1: Write the failing test for vlastník-only**

```python
# tests/test_build_zmena_fields.py
from app import build_zmena_fields

def test_vlastnik_only_no_jiny_provozovatel():
    data = {
        "novy_jmeno": "JAN NOVAK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_ico": "",
        "novy_adresa": "HLAVNI 5, BRNO",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    f = build_zmena_fields(data)

    # Vehicle
    assert f["comb_1"] == "1AB2345"
    assert f["comb_2"] == "WBA3A5C51DF123456"
    assert f["Druh vozidla"] == "osobni automobil"

    # Vlastník
    assert f["fill_2"] == "JAN NOVAK"
    assert f["comb_3"] == "850101/1234"
    assert f["comb_4"] == ""  # no IČO for fyzická osoba
    assert f["Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 1"] == "HLAVNI 5, BRNO"
    assert f["fill_6"] == "60200"

    # Provozovatel — must be blank when not jiný
    assert f["fill_7"] == ""
    assert f["fill_8"] == ""
    assert f["comb_5"] == ""
    assert f["comb_6"] == ""
    assert f["fill_11"] == ""

    # Žádá o provedení změny
    assert f["fill_12"] == "zápis A50-X"
    assert f["fill_13"] == ""
    assert f["fill_14"] == ""
    assert f["fill_15"] == ""
    assert f["fill_16"] == ""

    # Místo + datum
    assert f["V"] == "Brně"
    assert f["dne"]  # non-empty
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/test_build_zmena_fields.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_zmena_fields' from 'app'`.

- [ ] **Step 3: Implement minimum to pass**

Edit `app.py`. Add after `build_zapis_fields` (around line 620):

```python
def build_zmena_fields(data: dict) -> dict:
    tomorrow = _next_working_day()
    misto = "Brně"

    rc_combined = ""
    if data.get("novy_rc_1") or data.get("novy_rc_2"):
        rc_combined = f"{data.get('novy_rc_1','')}/{data.get('novy_rc_2','')}"

    if data.get("novy_prov_jiny"):
        prov_jmeno  = data.get("novy_prov_jmeno", "")
        prov_rc     = ""
        if data.get("novy_prov_rc_1") or data.get("novy_prov_rc_2"):
            prov_rc = f"{data.get('novy_prov_rc_1','')}/{data.get('novy_prov_rc_2','')}"
        prov_ico    = data.get("novy_prov_ico", "")
        prov_adresa = data.get("novy_prov_adresa", "")
        prov_psc    = data.get("novy_prov_psc", "")
    else:
        prov_jmeno = prov_rc = prov_ico = prov_adresa = prov_psc = ""

    addr_key_v = "Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 1"
    addr_key_v2 = "Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 2"
    addr_key_p = "Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 1_2"
    addr_key_p2 = "Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 2_2"

    return {
        # Vehicle
        "comb_1":       data.get("registracni_znacka", ""),
        "comb_2":       data.get("vin", ""),
        "Druh vozidla": data.get("druh_vozidla", ""),

        # Vlastník
        "fill_2":   data.get("novy_jmeno", ""),
        "fill_3":   "",
        "comb_3":   rc_combined,
        "comb_4":   data.get("novy_ico", ""),
        addr_key_v:  data.get("novy_adresa", ""),
        addr_key_v2: "",
        "fill_6":   data.get("novy_psc", ""),

        # Provozovatel (blank if not jiný)
        "fill_7":   prov_jmeno,
        "fill_8":   "",
        "comb_5":   prov_rc,
        "comb_6":   prov_ico,
        addr_key_p:  prov_adresa,
        addr_key_p2: "",
        "fill_11":  prov_psc,

        # Žádá o provedení změny — first line only
        "fill_12":  data.get("zadost_zmena", ""),
        "fill_13":  "",
        "fill_14":  "",
        "fill_15":  "",
        "fill_16":  "",

        # Místo + datum
        "V":   misto,
        "dne": tomorrow,
    }
```

- [ ] **Step 4: Run to confirm pass**

Run: `pytest tests/test_build_zmena_fields.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_build_zmena_fields.py app.py
git commit -m "feat(backend): add build_zmena_fields with vlastník-only path"
```

---

## Task 3: TDD — `build_zmena_fields` jiný-provozovatel path + právnická osoba

**Files:**
- Modify: `tests/test_build_zmena_fields.py` (add 2 cases)

- [ ] **Step 1: Add jiný-provozovatel test**

Append to `tests/test_build_zmena_fields.py`:

```python
def test_jiny_provozovatel():
    data = {
        "novy_jmeno": "VLASTNIK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_adresa": "ADRESA 1",
        "novy_psc": "60200",
        "novy_prov_jiny": True,
        "novy_prov_jmeno": "PROVOZOVATEL",
        "novy_prov_rc_1": "900101",
        "novy_prov_rc_2": "5678",
        "novy_prov_ico": "12345678",
        "novy_prov_adresa": "JINA 5",
        "novy_prov_psc": "11000",
    }
    f = build_zmena_fields(data)
    assert f["fill_7"] == "PROVOZOVATEL"
    assert f["comb_5"] == "900101/5678"
    assert f["comb_6"] == "12345678"
    assert f["fill_11"] == "11000"


def test_pravnicka_osoba_uses_ico_only():
    data = {
        "novy_jmeno": "FIRMA s.r.o.",
        "novy_rc_1": "",
        "novy_rc_2": "",
        "novy_ico": "12345678",
        "novy_adresa": "SIDLO 10",
        "novy_psc": "60200",
        "novy_prov_jiny": False,
    }
    f = build_zmena_fields(data)
    assert f["comb_3"] == ""  # no RČ
    assert f["comb_4"] == "12345678"
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/test_build_zmena_fields.py -v`
Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_build_zmena_fields.py
git commit -m "test: cover jiný provozovatel and právnická osoba paths"
```

---

## Task 4: Add `PDF_ZMENA` constant + startup field sanity check

(Done before the golden-file render test in Task 5 because that test imports `PDF_ZMENA`.)

**Files:**
- Modify: `app.py` (line 56, right after `PDF_ZAPIS`; and a validator block after `FIRMY_XLSX`)

- [ ] **Step 1: Add `PDF_ZMENA` constant**

In `app.py`, after the existing `PDF_ZAPIS` line (line 56):

```python
PDF_ZMENA = os.path.join(BASE_DIR, "pdfs", "zmena_udaju.pdf")
```

- [ ] **Step 2: Add expected-field validator**

After the `os.makedirs(SCANS_DIR, exist_ok=True)` block (line ~62), add:

```python
import logging as _logging
_log = _logging.getLogger("prepis")

_EXPECTED_FIELDS = {
    PDF_ZMENY: {"comb_1", "comb_2", "fill_2", "vlastníka", "provozovatele"},
    PDF_ZAPIS: {"Text3", "comb_3", "comb_5", "comb_1_2", "Check Box18"},
    PDF_ZMENA: {"comb_1", "comb_2", "Druh vozidla", "fill_2", "comb_3", "comb_4",
                "fill_6", "fill_7", "comb_5", "comb_6", "fill_11", "fill_12", "V", "dne"},
}

def _validate_pdf_templates():
    for path, expected in _EXPECTED_FIELDS.items():
        try:
            r = PdfReader(path)
            got = set((r.get_fields() or {}).keys())
            missing = expected - got
            if missing:
                _log.warning("PDF %s missing expected fields: %s", os.path.basename(path), sorted(missing))
        except Exception as e:
            _log.warning("Could not validate PDF %s: %s", os.path.basename(path), e)

_validate_pdf_templates()
```

- [ ] **Step 3: Run all backend tests**

Run: `pytest tests/ -v`
Expected: all pass (Tasks 1-3 still green).

- [ ] **Step 4: Run app smoke test**

Run: `python app.py &` then check terminal output for any WARNING. Kill the server.
Expected: no missing-field warnings.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat(backend): add PDF_ZMENA constant + startup template validation"
```

---

## Task 5: Golden-file PDF render test

**Files:**
- Create: `tests/test_pdf_render_zmena.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_pdf_render_zmena.py
"""Render zmena_udaju.pdf with a known field map and verify /V annotations match."""
import io
from pypdf import PdfReader
from app import fill_pdf, build_zmena_fields, PDF_ZMENA


def test_render_round_trip():
    data = {
        "novy_jmeno": "TESTOVACI VLASTNIK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_ico": "",
        "novy_adresa": "TESTOVACI ADRESA 1",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    fields = build_zmena_fields(data)
    pdf_bytes = fill_pdf(PDF_ZMENA, fields)
    assert len(pdf_bytes) > 1000  # sanity

    reader = PdfReader(io.BytesIO(pdf_bytes))
    rendered = reader.get_fields() or {}

    def v(name): return str(rendered[name].get("/V") or "")

    # fill_pdf uppercases all text fields EXCEPT NO_UPPER = {V, V_2, V_3, V_4, dne, dne_2, dne_3, dne_4}.
    # zadost_zmena → fill_12 IS uppercased; V is not.
    assert "1AB2345" in v("comb_1")
    assert "WBA3A5C51DF123456" in v("comb_2")
    assert "TESTOVACI VLASTNIK" in v("fill_2")
    assert "850101/1234" in v("comb_3")
    assert v("fill_7") == ""    # provozovatel jméno blank
    assert v("fill_11") == ""   # provozovatel PSČ blank
    assert "ZÁPIS A50-X" in v("fill_12")
    assert v("V") == "Brně"     # NOT uppercased
```

- [ ] **Step 2: Run to confirm pass**

Run: `pytest tests/test_pdf_render_zmena.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pdf_render_zmena.py
git commit -m "test: golden-file PDF render for zmena mode"
```

---

## Task 6: `/api/generate` branch + unknown-mode guard

**Files:**
- Create: `tests/test_generate_route_zmena.py`
- Modify: `app.py` (the `/api/generate` route, around line 781)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generate_route_zmena.py
import os
import json


def test_generate_zmena_returns_url(client, tmp_path, monkeypatch):
    payload = {
        "mode": "zmena",
        "novy_jmeno": "JAN NOVAK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_adresa": "ADRESA 1",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["zmena"].startswith("/download/zmena_")
    assert "zmeny" not in data
    assert "zapis" not in data


def test_generate_unknown_mode_returns_400(client):
    r = client.post("/api/generate", json={"mode": "neznamy"})
    assert r.status_code == 400
    data = r.get_json()
    assert data["success"] is False
    assert "neznámý" in data["error"].lower()
```

- [ ] **Step 2: Run to confirm fail**

Run: `pytest tests/test_generate_route_zmena.py -v`
Expected: 2 FAIL — current route returns success for any mode.

- [ ] **Step 3: Add unknown-mode guard at top of `/api/generate`**

In `app.py`, near line 776 (right after `mode = data.get("mode", "prevod")`):

```python
    if mode not in {"prevod", "zapis", "zmena"}:
        return jsonify({"success": False, "error": f"Neznámý mód: {mode}"}), 400
```

- [ ] **Step 4: Add zmena branch + ID overlay logic**

Find the `if mode == "prevod": ... else: # zapis...` block and replace with:

```python
    if mode == "prevod":
        zmeny_bytes = fill_pdf(PDF_ZMENY, build_zmeny_fields(data))
        zapis_bytes = fill_pdf(PDF_ZAPIS, build_zapis_fields(data))
        if zmeny_overlays: zmeny_bytes = add_id_overlay(zmeny_bytes, zmeny_overlays)
        if zapis_overlays: zapis_bytes = add_id_overlay(zapis_bytes, zapis_overlays)
        fname_zmeny = os.path.join(out_dir, f"zmeny_{ts}.pdf")
        fname_zapis = os.path.join(out_dir, f"zapis_{ts}.pdf")
        with open(fname_zmeny, "wb") as f: f.write(zmeny_bytes)
        with open(fname_zapis, "wb") as f: f.write(zapis_bytes)
        result["zmeny"] = f"/download/zmeny_{ts}.pdf"
        result["zapis"] = f"/download/zapis_{ts}.pdf"
    elif mode == "zmena":
        zmena_bytes = fill_pdf(PDF_ZMENA, build_zmena_fields(data))
        zmena_overlays = []
        if _id_text(data.get("novy_id")):
            zmena_overlays.append((0, 554, 700, _id_text(data["novy_id"])))
        if data.get("novy_prov_jiny") and _id_text(data.get("novy_prov_id")):
            zmena_overlays.append((0, 554, 555, _id_text(data["novy_prov_id"])))
        if zmena_overlays:
            zmena_bytes = add_id_overlay(zmena_bytes, zmena_overlays)
        fname = os.path.join(out_dir, f"zmena_{ts}.pdf")
        with open(fname, "wb") as f: f.write(zmena_bytes)
        result["zmena"] = f"/download/zmena_{ts}.pdf"
    else:  # zapis
        zapis_bytes = fill_pdf(PDF_ZAPIS, build_zapis_fields(data))
        if zapis_overlays: zapis_bytes = add_id_overlay(zapis_bytes, zapis_overlays)
        fname_zapis = os.path.join(out_dir, f"zapis_{ts}.pdf")
        with open(fname_zapis, "wb") as f: f.write(zapis_bytes)
        result["zapis"] = f"/download/zapis_{ts}.pdf"
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_generate_route_zmena.py app.py
git commit -m "feat(backend): add zmena branch in /api/generate + unknown-mode guard"
```

---

## Task 7: Frontend — third mode-card + flow definition

**Files:**
- Modify: `templates/index.html` (mode-card section ~line 279, flows object ~line 667)

- [ ] **Step 1: Add the third mode-card**

After the existing `data-mode="zapis"` card (line ~283), add:

```html
<div class="mode-card" data-mode="zmena" onclick="selectMode(this)" tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.stopPropagation();selectMode(this);}">
  <div class="mode-icon">🔧</div>
  <div>
    <div class="mode-title">Změna technických údajů</div>
    <div class="mode-desc">Změny v registru (zápis A50-X, ...). Generuje zmena_udaju.pdf.</div>
  </div>
</div>
```

- [ ] **Step 2: Add flow definition**

The actual variable in code is `FLOWS` (uppercase) at line 666. **Do not change the existing `prevod` or `zapis` entries** — preserve their panel order (zapis is `[1,3,4,5]` = Typ → Nový → Vozidlo → Generovat, intentionally fills owner before vehicle so OP-scan data flows naturally). Add only the third entry, matching zapis ordering:

```js
const FLOWS = {
  prevod: { panels: [1,4,2,3,5], labels: ['Typ','Vozidlo','Původní','Nový','Generovat'] },
  zapis:  { panels: [1,3,4,5],   labels: ['Typ','Nový','Vozidlo','Generovat'] },
  zmena:  { panels: [1,3,4,5],   labels: ['Typ','Vlastník','Vozidlo','Generovat'] },
};
```

- [ ] **Step 3: Smoke test in dev mode**

Run: `python app.py` in one terminal, browse to http://localhost:5050.
Click the third mode-card. Verify the wizard advances through 4 steps with the right labels.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(frontend): add zmena mode-card and flow definition"
```

---

## Task 8: Frontend — `vozidlo-zmena-fields` div on Vehicle panel

**Files:**
- Modify: `templates/index.html` (panel-4 section ~line 504, activatePanel(4) ~line 759)

- [ ] **Step 1: Add the third sub-block to panel-4**

After the existing `vozidlo-zapis-fields` div (line ~614), add:

```html
<!-- Zmena-only -->
<div id="vozidlo-zmena-fields" style="display:none;">
  <div class="form-grid">
    <div class="field">
      <label>Registrační značka</label>
      <input type="text" id="registracni_znacka_zm" placeholder="1AB2345">
    </div>
    <div class="field">
      <label>VIN</label>
      <input type="text" id="vin_zm" placeholder="WBA3A5C51DF123456" maxlength="17" style="font-family:monospace;letter-spacing:.06em;">
    </div>
    <div class="field">
      <label>Druh vozidla</label>
      <select id="druh_vozidla_zm">
        <option value="osobni automobil" selected>Osobní automobil</option>
        <option value="nakladni automobil">Nákladní automobil</option>
        <option value="motocykl">Motocykl</option>
        <option value="pripojne vozidlo">Přípojné vozidlo</option>
        <option value="autobus">Autobus</option>
        <option value="traktor">Traktor</option>
      </select>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Update `activatePanel(4)` visibility toggle**

Find the lines (around 759-760):

```js
document.getElementById('vozidlo-prevod-fields').style.display = appMode === 'prevod' ? '' : 'none';
document.getElementById('vozidlo-zapis-fields').style.display  = appMode === 'zapis'  ? '' : 'none';
```

Add a third line:

```js
document.getElementById('vozidlo-zmena-fields').style.display  = appMode === 'zmena'  ? '' : 'none';
```

- [ ] **Step 3: Smoke test**

Run dev server, click the zmena card, advance to Vozidlo panel. Verify only RZ + VIN + Druh inputs are shown (no ORV, no jiný doklad, no zmena typ radios).

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(frontend): add vozidlo-zmena-fields sub-block"
```

---

## Task 9: Frontend — "Žádá o provedení změny" section on Vlastník panel

**Files:**
- Modify: `templates/index.html` (panel 3 — find by searching for `id="novy_id"` or similar; add at the bottom of the panel)

- [ ] **Step 1: Add the section markup**

At the end of the Nový vlastník panel (look for the closing `</div>` of the panel, before the panel-4 element), add:

```html
<div id="zmena-changes-section" style="display:none;">
  <hr class="divider">
  <div class="section-label">Žádá o provedení změny</div>
  <div class="form-grid">
    <div class="field full">
      <input type="text" id="zadost_zmena" maxlength="80" placeholder="napr. zápis A50-X" style="font-size:14px;">
    </div>
  </div>
  <div style="display:flex;gap:8px;margin-top:8px;">
    <button type="button" onclick="document.getElementById('zadost_zmena').value='zápis A50-X'" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;font-size:13px;">zápis A50-X</button>
    <button type="button" onclick="document.getElementById('zadost_zmena').value='zápis'" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;font-size:13px;">zápis</button>
  </div>
</div>
```

- [ ] **Step 2: Toggle visibility based on `appMode`**

Locate `selectMode()` in `templates/index.html` (search `function selectMode`). At its end (after the line that sets `appMode = el.dataset.mode;` around line 716), add:

```js
const zs = document.getElementById('zmena-changes-section');
if (zs) zs.style.display = appMode === 'zmena' ? '' : 'none';
```

This guarantees the section toggles on every mode change, regardless of which panel is currently active.

- [ ] **Step 3: Smoke test**

Click zmena mode → advance to Vlastník panel → see the "Žádá o provedení změny" section with two preset buttons. Click one — input should populate.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(frontend): add Žádá o provedení změny section"
```

---

## Task 10: Frontend — payload + result rendering for zmena

**Files:**
- Modify: `templates/index.html` (payload-build code ~line 1189-1235, result handler ~line 1246, printAll ~line 1278)

- [ ] **Step 1: Update payload builder**

Find the lines reading `vin` / `vin_z`. Change the relevant entries to:

```js
vin:                 appMode === 'prevod' ? v('vin') : (appMode === 'zapis' ? v('vin_z') : v('vin_zm')),
registracni_znacka:  appMode === 'prevod' ? v('registracni_znacka') : (appMode === 'zmena' ? v('registracni_znacka_zm') : ''),
druh_vozidla:        appMode === 'prevod' ? v('druh_vozidla') : (appMode === 'zapis' ? v('druh_vozidla_z') : v('druh_vozidla_zm')),
zadost_zmena:        appMode === 'zmena' ? v('zadost_zmena') : '',
```

- [ ] **Step 2: Add `btn-zmena` element to output card**

Find `btn-zmeny` and `btn-zapis` links in the output-card. Add adjacent:

```html
<a id="btn-zmena" class="btn-download" target="_blank" style="display:none;">📄 Stáhnout zmena.pdf</a>
```

- [ ] **Step 3: Update result handler**

Replace ONLY the `generatedUrls = ...` line and the next 2 lines (1246-1248) with the loop below. **Do NOT touch the plné moci block at lines 1250-1260** — keep it intact:

```js
generatedUrls = { zmeny: result.zmeny, zapis: result.zapis, zmena: result.zmena, plne_moce: result.plne_moce || [] };
for (const [key, btnId] of [['zmeny','btn-zmeny'], ['zapis','btn-zapis'], ['zmena','btn-zmena']]) {
  const url = result[key];
  const btn = document.getElementById(btnId);
  if (!btn) continue;
  if (url) { btn.href = url; btn.style.display = ''; }
  else     { btn.style.display = 'none'; }
}
```

- [ ] **Step 4: Update `printAll()`**

Replace:

```js
function printAll() {
  ['zmeny','zapis','zmena'].forEach(k => { if (generatedUrls[k]) window.open(generatedUrls[k], '_blank'); });
  (generatedUrls.plne_moce || []).forEach(url => window.open(url, '_blank'));
}
```

- [ ] **Step 5: End-to-end smoke test**

Click zmena → fill all 4 steps → click Generovat → verify "Stáhnout zmena.pdf" button appears, downloads work, printAll opens the PDF.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat(frontend): wire payload + result rendering for zmena mode"
```

---

## Task 11: Frontend — summary screen row for `zadost_zmena`

**Files:**
- Modify: `templates/index.html` (summary-building code, search for `appMode === 'prevod'` near summary)

- [ ] **Step 1: Add summary row**

Locate the summary-building code (around line 1142). After existing rows, before VIN row, add:

```js
if (appMode === 'zmena' && v('zadost_zmena')) {
  html += row('Žádá o změnu', v('zadost_zmena'));
}
```

- [ ] **Step 2: Smoke test**

End-to-end: zmena mode → fill including zadost_zmena → review screen shows "Žádá o změnu: zápis A50-X".

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat(frontend): show zadost_zmena in summary screen"
```

---

## Task 12: ID overlay coordinate measurement

**Files:**
- Modify: `app.py` (the y-coordinates in zmena_overlays from Task 6)

- [ ] **Step 1: Generate a test PDF with placeholder IDs**

Run dev server, fill the form with `novy_id = "1234567890"` and `novy_prov_id = "9876543210"` (with `novy_prov_jiny=true`). Generate the PDF.

- [ ] **Step 2: Open the PDF and visually inspect**

Check whether `ID: 1234567890` overlays correctly under the vlastník jméno field (right edge, just below) and `ID: 9876543210` under the provozovatel jméno field. Record any visual mis-alignment.

- [ ] **Step 3: Adjust y-coordinates**

If overlays are too high/low, edit the `zmena_overlays.append((0, 554, Y, ...))` calls in `/api/generate`. Iterate ±20 px until visually correct.

- [ ] **Step 4: Commit final coords**

```bash
git add app.py
git commit -m "fix(backend): tune zmena ID overlay y-coordinates"
```

---

## Task 13: Version bump + build + deploy

**Files:**
- Modify: `VERSION` (1.0.19 → 1.1.0)
- Modify: `version.py`
- Modify: `app.py` (`__version__`)

- [ ] **Step 1: Bump VERSION file**

Edit `VERSION`: write `1.1.0\n`.

- [ ] **Step 2: Bump `version.py`**

Edit: `__version__ = "1.1.0"`.

- [ ] **Step 3: Bump `app.py` `__version__`**

Confirmed location: `app.py` line 24 contains `__version__ = "1.0.19"`. Change to `__version__ = "1.1.0"`.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`
Expected: all pass.

- [ ] **Step 5: Build**

Run: `python -m PyInstaller prepis_vozidla.spec --noconfirm`
Expected: ends with `Build complete!`.

- [ ] **Step 6: Verify VERSION in dist**

Check: `dist/PrepisVozidla/_internal/VERSION` contains `1.1.0`. Check: `dist/PrepisVozidla/_internal/pdfs/zmena_udaju.pdf` exists.

- [ ] **Step 7: Coordinate with Petr**

Tell user: "Petr needs to close PrepisVozidla on his end so deploy can complete."

- [ ] **Step 8: Deploy to NAS**

Run: `deploy_to_nas.bat` (or PowerShell copy). Verify `\\192.168.1.18\Petr\PrepisVozidla\_internal\VERSION` contains `1.1.0`.

- [ ] **Step 9: Commit version bump**

```bash
git add VERSION version.py app.py
git commit -m "chore: bump to 1.1.0 — adds Změna technických údajů mode"
```

- [ ] **Step 10: Smoke test deployed exe**

Local: kill any running PrepisVozidla, double-click the deployed exe (from %TEMP% via launcher, or directly from dist/), verify v1.1.0 in `/api/version` and that the third mode card appears.

---

## Done Criteria

All of:
- All pytest tests pass.
- All 13 tasks committed.
- Local smoke test from `dist/` shows v1.1.0 with three working modes.
- NAS has v1.1.0 deployed.
- Petr's running app, on next restart, picks up v1.1.0 and the new mode is functional.
