# PPD generator + results-page redesign + camera-on-reset — Design Spec

**Date:** 2026-06-02
**Status:** Draft
**Scope:** Three bundled changes to the web app (zadosti.spznaklic.cz):
1. Generate a **PPD** (příjmový pokladní doklad — cash receipt) automatically alongside each žádost.
2. **Redesign the results page** buttons into a small, clear set.
3. On **"Nová žádost"** (reset), return to step 1 with the camera already opening.

Web-only deployment (desktop deprecated). v1.1.10 → v1.2.0 (new feature → minor bump).

## Context

The app fills Czech vehicle-registry žádosti (převod / zápis / změna) and serves them as PDFs on a results page. ALSETA s.r.o. (the operator) charges a service fee (usually 1300 Kč) for handling the paperwork and currently writes the cash receipt (PPD) by hand. This adds an automated PPD to the existing generate flow, and tidies the results page.

## Decisions (confirmed with owner)

- **Issuer (fixed):** ALSETA s.r.o., IČO 07133880, **neplátce DPH** → receipt shows only the total, no VAT breakdown.
- **Payer ("Přijato od"):** auto-prefilled = provozovatel if "jiný provozovatel" is checked, else the (nový) vlastník. Editable before generating.
- **Amount:** default **1300 Kč**, editable. Rendered numerically and in words.
- **Purpose:** auto-composed from mode + RZ.
- **Receipt number:** plain sequential integer, starts at **1**, never repeats. (If the owner later wants to continue an existing paper series, the starting number is a one-line change.)
- **Always generated** alongside the žádost when amount > 0 (no opt-in checkbox); user ignores the print button if not needed.
- **num2words** dependency approved for Czech amount-in-words.
- **Standalone PPD section** (issue a receipt without a přepis) is **deferred** to a fast-follow; the core (`ppd.py`) is built so it can be reused.
- **"Nový přepis" relabeled to "Nová žádost"** (fits all three modes).

## Out of Scope

- Standalone PPD section (deferred — reuses this spec's `ppd.py`).
- VAT/DPH breakdown (issuer is neplátce).
- Editing/voiding already-issued receipts.
- Exact pixel-match to the owner's current paper PPD — layout follows the standard Czech PPD; refined against their sample later.

## Architecture

> **Revised after architect review (must-fix items folded in below).**

### New module: `ppd.py`

Keeps PPD logic out of the already-large `app.py`. Pure functions + small I/O helpers.

- `amount_to_words_cs(n: int) -> str`
  Czech words **with correct case declension** via
  `num2words(n, lang="cs", to="currency", currency="CZK")`.
  This handles koruna/koruny/korun agreement (1 koruna, 2 koruny, 5 korun, 1300 → "korun") — a plain `+ " korun českých"` concatenation would be grammatically wrong for most amounts. We strip/normalize the heller (".. haléřů") tail since amounts are whole crowns. Result example (1300): `"jeden tisíc tři sta korun českých"` (exact wording per num2words output; test asserts substrings, not the full string).

- `reserve_ppd_number_and_log(data_dir: str, record: dict) -> int`
  **Single source of truth, single lock.** Allocates the next number AND
  appends the evidence row under **one** `fcntl.flock` so the two can never
  diverge and two gunicorn workers can't race:
  1. `open(ppd_lock_path, "a+")`, `fcntl.flock(fd, LOCK_EX)` (blocking).
  2. Load `ppd_evidence.xlsx` (or create with header if missing); compute
     `number = max(existing Číslo column, 0) + 1` — the ledger itself is the
     counter, so there is no separate counter file to desync.
  3. Append the row `[number, date, payer, amount, purpose, vehicle]`.
  4. Atomic save: write to `ppd_evidence.xlsx.tmp`, `os.replace` over the
     real file (keep a `.bak` of the prior good file), `os.fsync` the temp
     fd before replace so a kill mid-write can't leave a partial ledger.
  5. `flock(LOCK_UN)` / close.
  Returns `number`. The PDF is built by the caller **after** the lock is
  released (the number is already durably reserved by the ledger row), so
  the slow reportlab render isn't inside the critical section.
  - `fcntl` is POSIX-only; guard the import. On Windows dev, fall back to a
    best-effort non-locked version (dev only — production is the Linux
    container, single NAS, where flock works).

- `build_ppd_pdf(record: dict) -> bytes`
  Draws an **A5 portrait** receipt with **reportlab** (`pagesize=A5` set
  explicitly — `add_id_overlay` hardcodes A4, do NOT copy that). Sections:
  Title `PŘÍJMOVÝ POKLADNÍ DOKLAD č. <number>`, issuer `ALSETA s.r.o.,
  IČO: 07133880` (neplátce DPH), `Datum`, `Přijato od`, `Částka <n> Kč`,
  `Slovy: <amount_to_words_cs>`, `Účel platby`, `Vystavil / Podpis` lines.
  - **Czech diacritics — MUST ship a Unicode TTF.** reportlab's built-in
    Helvetica is Latin-1 and renders ě/š/č/ř/ž as boxes; the built-in CID
    fonts are CJK, not Czech — neither works. Commit
    `static/fonts/DejaVuSans.ttf` (DejaVu is freely redistributable) — it is
    already bundled because the Dockerfile does `COPY static ./static`. Register
    it once at module load: `pdfmetrics.registerFont(TTFont("DejaVu", <path>))`
    and use it for every string. (`add_id_overlay` only ever drew digits, so
    its Helvetica was fine — PPD has real Czech text, so it is not.)

### Backend wiring (`app.py`)

- New helper `resolve_payer(data: dict) -> str` (used by both the PPD path
  and exposed logic): the payer is the **buyer / new owner side**, uniformly
  across all modes — `novy_prov_jmeno` if `novy_prov_jiny` is truthy, else
  `novy_jmeno`. **Never `puvodni_*`** (the architect flagged that for prevod
  the payer is the new owner/provozovatel, not the seller). The frontend
  prefill uses the same rule, so the backend value is just a fallback when
  `ppd_prijato_od` arrives empty.

In `/api/generate`, after the žádost PDFs are produced (all three mode
branches), wrapped in `try/except` so a PPD failure never breaks the žádost
response (log warning, omit `result["ppd"]`):
- `amount` = parse `data.get("ppd_castka")`; non-numeric → 1300; **≤ 0 → skip PPD entirely** (the opt-out).
- `payer = (data.get("ppd_prijato_od") or "").strip() or resolve_payer(data)`
- `purpose`:
  - prevod → `"Za vyřízení přepisu vozidla RZ <rz>"`
  - zapis → `"Za vyřízení registrace vozidla <rz nebo VIN>"`
  - zmena → `"Za vyřízení změny údajů vozidla RZ <rz>"`
- `number = ppd.reserve_ppd_number_and_log(DATA_DIR, {date, payer, amount, purpose, vehicle})`
- `pdf = ppd.build_ppd_pdf({number, date, payer, amount, purpose})`; save `output/ppd_<ts>.pdf`; `result["ppd"] = "/download/ppd_<ts>.pdf"`.

The unknown-mode guard and existing žádost generation are unchanged.

### Frontend (`index.html`)

**Generate step (panel 5):** add a compact "Doklad (PPD)" block above/below the summary with:
- `Částka za vyřízení (Kč)` — number input, default `1300`, id `ppd_castka`
- `Přijato od` — text input, id `ppd_prijato_od`, prefilled when panel 5 activates: provozovatel name if "jiný provozovatel" checked, else the (nový) vlastník name. Editable.

**Payload:** add `ppd_castka` and `ppd_prijato_od` to the `/api/generate` POST body.

**Results page — new button set** (replaces the per-document download buttons + "Vytisknout vše"):
1. **🖨️ Vytisknout žádost** — opens the mode's žádost PDF(s) in new tab(s) for printing (the existing `printAll` mechanism, which already reads `generatedUrls` and a hardcoded `['zmeny','zapis','zmena']` list + plné moci, so it is **already scoped** and does not touch PPD).
2. **🧾 Vytisknout PPD** — opens `result.ppd` (A5). Shown only when a PPD was generated.
3. **🛡️ Zkontrolovat pojištění (ČKP)** — unchanged.
4. **🔄 Nová žádost** — reset (relabeled from "Nový přepis").

The individual `btn-zmeny` / `btn-zapis` / `btn-zmena` button elements are removed **and** the result-handler loop that sets their `.href`/`.style.display` (currently lines ~1307-1313) is removed with them (it's `if(!btn) continue`-guarded so it wouldn't throw, but leaving it is dead code). `btn-pojisteni` keeps its separate wiring. Plné moci conditional links stay as-is below the buttons.

**Reconcile the existing auto-print on generate (architect catch):** today the Ctrl+Enter shortcut and the final generate step call `printAll()` automatically, so the žádost PDFs already auto-open in tabs. With the new manual-button layout this is removed — **generate just shows the results card; the user presses the print buttons.** No auto-open of either žádost or PPD (avoids A4/A5 tab spam and matches the "buttons to press" intent). Ctrl+Enter still triggers generate, just without the auto-print.

**Camera on reset:** `resetForm()` stays `location.reload()` (bulletproof state clear — an in-page reset would have to manually clear every field, wizard index, `generatedUrls`, `scanAllItems`, output card, which is error-prone). After reload, `activatePanel(1)` calls `tryAutoOpenCamera()`. **This environment is desktop Chrome with camera permission already granted** (verified working earlier in this project — the camera auto-opened on load during the ORV-scan testing), so gesture-less `getUserMedia` succeeds on reload; the one-shot `pointerdown` listener remains as fallback. (The architect's iOS-Safari concern doesn't apply — Petr uses the app on a PC in Chrome.) Verify once after deploy; only if observed broken do we switch to gesture-preserving in-page reset.

### Dependencies / build

- Add `num2words` to `requirements.txt`.
- Bump `Dockerfile` `CACHEBUST`.
- Bump version 1.1.10 → 1.2.0 (VERSION, version.py, app.py).

## Testing

- **Unit (`tests/test_ppd.py`):**
  - `amount_to_words_cs(1300)` → contains "tisíc" and "korun" (assert substrings, tolerant of spacing/wording); `(1)` → contains "koruna"; `(5)` → "korun"; `(22)` → "koruny" (declension sanity from the currency mode).
  - `reserve_ppd_number_and_log` — first call on a fresh temp `data_dir` returns 1; subsequent calls return 2, 3…; numbers persist (re-read derives max from the evidence xlsx); each call adds exactly one row.
  - `build_ppd_pdf` — returns bytes starting with `%PDF`; `pypdf.extract_text()` of the result contains the number, payer name, amount, and the Czech words (proves the TTF renders diacritics, not boxes).
- **Integration (`tests/test_generate_ppd.py`):**
  - POST `/api/generate` (mode=prevod) with `ppd_castka=1300`, `ppd_prijato_od="PETR KUPUJÍCÍ"` → response has `ppd` URL; file exists; `ppd_evidence.xlsx` got a row.
  - POST with `ppd_castka=0` → no `ppd` key (opt-out), žádosti still returned.
- Existing 6 tests must stay green. (`num2words` must be `pip install`-ed locally for the unit tests to run.)

## Error Handling

- PPD generation wrapped in try/except — never blocks žádost output.
- Non-numeric/empty amount → default 1300; amount ≤ 0 → skip PPD.
- Counter file unreadable → log warning, fall back to `max(existing evidence numbers)+1` or 1.
- Czech diacritics: must render correctly on the A5 PDF — verified by the golden-text test + a visual check after deploy.

## Versioning + Deploy

- v1.2.0. Sync source → `docker compose build --no-cache --pull` → `up -d` on the NAS (existing `scripts/nas_deploy.py` flow). Verify health + visual check of a generated PPD.

## Open refinement (post-ship, not blocking)

- Match the owner's existing paper PPD layout once they provide the sample.
- Standalone PPD section (issue a receipt without a přepis), reusing `ppd.py`.
- Configurable starting receipt number if they want to continue a paper series.
