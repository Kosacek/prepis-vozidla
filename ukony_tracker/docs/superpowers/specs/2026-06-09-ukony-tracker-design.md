# Úkony Tracker — Design Spec

**Date:** 2026-06-09
**Status:** Draft for review (rev 3 — post multi-lens review, approved)
**Author:** David (with Claude)
**Location:** `prepis_vozidla_app/ukony_tracker/` (standalone app, sibling to `prepis_app/`, same git repo)

---

## 1. Summary

A standalone local web app that replaces the manual Excel workbook David uses to record every vehicle administrative *úkon* (transfer, new registration, import, export, etc.) he performs for car dealerships ("firmy"). Today each firm is a separate sheet in a monthly `.xlsx` file (`5.2026.xlsx`), with one row per úkon: `Datum · RZ · Úkon · Celkem · VIN · Poznámka`.

The new app keeps that exact mental model — **pick a firm, add úkony** — but in a clean Apple-style UI, adds a **dashboard with monthly revenue trends**, and adds **payment tracking** (paid / partially paid + amount received) so cash payments are recorded instead of tracked in his head. It is an **income record for tax/accounting purposes**, not an invoicing tool.

It is built on the same stack as the existing **Přepis Vozidla** app (Python/Flask) so that, in a future phase, completing a žádost in that app can automatically push the úkon into this tracker.

---

## 2. Goals

- Record úkony per firm, as fast as typing rows in Excel (faster, with price auto-fill).
- Show a dashboard: month KPIs, **monthly revenue trend graph**, per-firm breakdown, per-type breakdown, recent activity.
- Track payment status and amount received per úkon; surface outstanding (unpaid) totals.
- Produce **accurate monthly and yearly totals** and **export to Excel/CSV** that matches what the accountant files.
- Store data safely (it is a tax record): robust storage, auto-backup, no silent data loss.
- Be architected so the Přepis app can later push úkony in without a rewrite.
- **ARES lookup by IČO is an intentional v1 inclusion** (reused from `prepis_app`'s verified lookup hitting the free `ares.gov.cz` REST endpoint) — it adds one external network dependency to v1 and that is a conscious decision.

## 3. Non-Goals (v1)

- **Invoicing / billing statements** — not needed; this is an income record, not an invoice generator.
- **Žádost → auto-log wiring** — the ingestion path is *designed and built* (service + endpoint), but the Přepis app is *not* modified to call it in v1.
- **OCR / document scanning** to auto-fill RZ+VIN — deferred to the future Přepis-app integration (the data will arrive automatically then).
- **Extra per-úkon fields** (vehicle brand/model, customer name) — kept lean; only the existing Excel columns + payment fields.
- **Multi-user / authentication** — single user (David) on his PC.
- **Mobile-first polish** — desktop-first; usable on a phone but not optimized for it.
- **Historical import** of pre-May-2026 data — starting fresh; only May 2026 is seeded.
- **Fuzzy / auto-create firm matching** in the ingestion API — deferred to the future wiring phase (see §9).

## 4. Users & Context

- Single user: David, a freelancer who processes ~5–20 úkony/day at the Brno úřad for several car dealerships.
- Primary usage: **desktop**, batch entry (e.g. evening) and dashboard review on a big screen. Phone is rare.
- Runs **locally** like the current Přepis app (separate port, see §10).

### 4.1 Source data files (hard prerequisites for seeding)

Both must be present before `seed.py` and the data-layer tests can run:

| File | Repo path | Layout |
|---|---|---|
| Firms list | `prepis_app/firmy.xlsx` (already in repo) | Single sheet `Firmy`, columns: `Název, IČO, Adresa, PSČ, ID`. **9 data rows** (no short-name/zkratka column — see §5.1/§12). |
| May 2026 úkony | `ukony_tracker/scripts/seed_data/5.2026.xlsx` (copied into repo on 2026-06-09) | **One sheet per firm**: `Albion`, `Cardion`, `Orbion`. Columns: `Datum, RZ, Úkon, Celkem, VIN, Poznámka`. Col 7 holds a firm **shortcode** (`ALB`/`CARD`/`ORB`) — this is NOT the `zkratka` label (see §12). |

**File quirks the seeder must handle (verified against the on-disk file):** each sheet ends with one **manual subtotal row that has a Celkem but no Datum** (Albion row 49 = 44 500, Cardion row 120 = 84 400, Orbion row 69 = 16 800 — each equals that sheet's data-row sum), and Albion has one stray non-úkon numeric value in the VIN column (row 80). These must be **skipped** on import (§12 step 3). Counting only datum-bearing rows, the true data is **90 úkony / 145 700 Kč** (Albion 18 / 44 500, Cardion 59 / 84 400, Orbion 13 / 16 800). Summing the subtotal rows as well double-counts to 291 400 Kč — that is a bug to avoid, not the real total.

**Data privacy:** `ukony_tracker/data/` (the live DB + backups) and `ukony_tracker/scripts/seed_data/` (real income data) are **gitignored** — personal financial data stays out of version control. The files exist locally; they are not committed.

---

## 5. Domain Model

### 5.1 Entities

**`firmy`** — the dealerships work is done for. Exactly **9 firms** seeded (from `firmy.xlsx`):
Albion Cars s.r.o. (IČO 04168313), AUTO CARDION s. r. o. (04156854), EV trans s.r.o. (06583539), JE & NE, spol. s r.o. (44960263), Leasing České spořitelny, a.s. (27089444), MONETA Auto, s.r.o. (60112743), ORBION CARS s.r.o. (21231800), Raiffeisen - Leasing, s.r.o. (61467863), ŠkoFIN s.r.o. (45805369).

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | app's own id |
| nazev | TEXT NOT NULL | full legal name, e.g. "AUTO CARDION s. r. o." |
| zkratka | TEXT NOT NULL | short tab label, e.g. "Cardion". Derivation in §12. Editable in the Firmy screen. |
| ico | TEXT | 8 digits; nullable; used for firm resolution (§9) and ARES |
| adresa | TEXT | nullable |
| psc | TEXT | nullable |
| aktivni | INTEGER (bool) | default 1; inactive firms hidden from tabs but kept for history |
| poradi | INTEGER NOT NULL | tab ordering (§12) |
| legacy_id | INTEGER | the `ID` column from `firmy.xlsx` (nullable; present for only 2 firms). Stored, not used in v1; reserved for future Přepis matching. |

New firms addable in-app, with **ARES lookup by IČO** (reusing the same free ARES endpoint the Přepis app uses) to auto-fill nazev/adresa/psc.

**`typy_ukonu`** — the price list / číselník.
| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| kod | TEXT NOT NULL UNIQUE | e.g. "PŘEVOD", "NOVÉ", "DOVOZ", "VÝVOZ", "ORV", "3RZ" |
| vychozi_cena | REAL | base price auto-filled on entry; nullable (null = no auto-fill, user types Celkem) |
| poradi | INTEGER | display order |
| aktivni | INTEGER (bool) | default 1 |

**Seeded types and base prices** (each is the *modal* Celkem for that type in the source data — verified): PŘEVOD 1300, NOVÉ 1300, DOVOZ 2000, VÝVOZ 1000, ORV 1000, 3RZ 1200. Editable in Settings.

**Pricing rule (important):** `ukony.celkem` is the **single source of truth** for money. `typy_ukonu.vychozi_cena` is only an **editable hint** that pre-fills the Cena field when a type is picked; the user overrides it whenever the real price differs (e.g. PŘEVOD with RZ-na-přání is 11 800, with TZ/PM surcharges 1400–1600). No base-price-plus-surcharge calculation is modeled in v1 — the user just types the actual Celkem. Aggregations and exports always use `celkem`, never `vychozi_cena`.

**`ukony`** — the records (one row = one úkon).
| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| firma_id | INTEGER FK → firmy.id NOT NULL | |
| datum | TEXT (ISO date) NOT NULL | defaults to today on entry |
| rz | TEXT | registrační značka / SPZ; **free-form** (data also contains codes like `K56010`, `P26226`); nullable |
| typ_kod | TEXT NOT NULL | references `typy_ukonu.kod`; **required at entry** (the segmented control always has a selection — default PŘEVOD). Stored as text so historical rows survive type edits. |
| celkem | REAL NOT NULL | price charged, Kč (the "Celkem" column) |
| vin | TEXT | last digits or code; **free-form**, nullable |
| poznamka | TEXT | free text; nullable. Common content: TZ, PM, RZ/RZP, EL |
| stav_platby | TEXT NOT NULL | one of: `nezaplaceno` \| `zaplaceno` \| `castecne`; default `nezaplaceno` |
| zaplaceno_kc | REAL NOT NULL | amount received so far, Kč; default 0; constraint 0 ≤ zaplaceno_kc ≤ celkem |
| zdroj | TEXT NOT NULL | `rucni` \| `prepis_app`; default `rucni` (provenance for the future integration) |
| created_at | TEXT (ISO datetime) | |
| updated_at | TEXT (ISO datetime) | |

**Outstanding (dlužné)** for an úkon = `celkem − zaplaceno_kc`. Marking "zaplaceno" sets `zaplaceno_kc = celkem`. Entering a partial amount 0 < x < celkem sets `castecne`.

### 5.2 Notes / tags

`poznamka` stays **free text** (matches current usage). The entry UI offers a **canonical one-tap chip set: `TZ`, `PM`, `RZ`** that *append* text to the poznámka field. This is a convenience shortcut, **not an exhaustive tag list** — other content (RZP, EL, anything) is typed freely. No structured tag entity in v1.

---

## 6. Screens

### 6.1 Přidat úkony (entry) — primary screen, **Layout A** (approved)

- **Firm selector at top**: pill row of firms (the `zkratka` is the label; active firm highlighted), `+ firma` to add a new one. Selecting a firm scopes the screen to that firm.
- **Month line**: current month with a selector (`Květen 2026 ▾`) and the firm's running total for that month (e.g. `59 úkonů · 84 400 Kč`).
- **"Nový úkon" card** (the hero): spacious form — Datum (default today), RZ, **Typ úkonu** as a segmented control (**default-selected, never empty**; selecting a type **auto-fills Cena** from `vychozi_cena`, editable), Cena, VIN, Poznámka with `TZ / PM / RZ` chips, and a primary **Přidat úkon** button.
  - After submit: row is saved, fields reset (Datum stays = today, type stays = last used), focus returns to RZ for rapid sequential entry.
- **Separator + "Tento měsíc" list** *below* the card (clear whitespace, not crammed): airy list of that firm's úkony for the selected month with payment indicator, and "Zobrazit všech N úkonů →" linking to the full table.
- Visual style: Apple-like (system font, light-gray canvas `#f5f5f7`, white rounded cards, single blue accent). See §14 for the fallback default vs. David's reference.

### 6.2 Přehled (dashboard)

- **KPI cards**: úkonů this month; revenue this month; year-to-date revenue; **outstanding (nezaplaceno) total**.
- **Měsíční tržby**: monthly trend graph (Chart.js) with a year selector. Default metric **revenue (Kč)**, toggle to **počet úkonů**.
- **Typy úkonů**: breakdown (donut or bar) of úkon types for the selected period. Since `typ_kod` is required, no untyped bucket is needed.
- **Podle firmy**: per-firm breakdown with a toggle revenue ↔ count and month ↔ year.
- **Poslední úkony**: recent activity feed across all firms.
- Empty/low-data state handled gracefully (fresh start = one month of data).

### 6.3 Úkony (full table)

- Filterable/sortable table across all firms or one firm: filter by firma, month/year, typ, payment status.
- Inline **edit** and **delete** (delete asks for confirmation).
- Quick **mark paid** action (sets `zaplaceno_kc = celkem`, `stav_platby = zaplaceno`) or enter a partial amount.
- Replaces flipping between Excel sheets.

### 6.4 Firmy (management)

- List firms; add/edit `nazev`/`zkratka`/`ico`/`adresa`/`psc`; toggle `aktivni`; reorder (`poradi`). **ARES lookup by IČO** auto-fills nazev/adresa/psc.

### 6.5 Nastavení (settings)

- Manage `typy_ukonu`: add/edit/reorder types and base prices.
- Export entry point (also reachable from dashboard/firma): see §8.

---

## 7. Key Flows

1. **Add an úkon**: select firm → date=today pre-filled → type RZ → pick type (Cena auto-fills) → optionally VIN/poznámka → Přidat → row appears in month list, totals update, focus resets.
2. **Record a cash payment**: in the úkon list/table, mark paid or enter amount received → `stav_platby`/`zaplaceno_kc` update → outstanding totals recompute.
3. **Review the month**: dashboard → KPIs, trend, per-firm/per-type breakdowns.
4. **Give the accountant the month**: Export → choose month/year (all firms or one) → download Excel (one-sheet-per-firma) or CSV.
5. **Add a new firm**: `+ firma` → enter IČO → ARES fills the rest → save → appears as a tab.

---

## 8. Export

- **Excel**: rebuilds the familiar **one-sheet-per-firma** workbook for a chosen month or whole year, columns as today (`Datum · RZ · Úkon · Celkem · VIN · Poznámka`), plus two appended payment columns:
  - **`Zaplaceno`** ← `stav_platby` enum (`nezaplaceno` / `zaplaceno` / `castecne`).
  - **`Zaplaceno Kč`** ← `zaplaceno_kc`.
  - Each firm sheet ends with a **totals row** in the `Celkem` column (sum of that firm's úkony for the period) and a count; the workbook matches the dashboard figures.
- **CSV**: flat table (all firms, all columns incl. `firma`, payment columns) for any date range.
- Export totals are computed from the **same aggregation layer** the dashboard uses (single source of truth for numbers); `export_service` tests assert exact values and totals-row placement.

---

## 9. Future Integration (designed in v1, wired later)

- A single **`ingest_service.pridat_ukon(...)`** function is the *only* write path for creating an úkon; both the UI and a thin **`POST /api/ukony`** endpoint call it.
- The endpoint accepts an úkon payload: `firma_id` **or** `ico`, plus datum, rz, typ_kod, celkem, vin, poznamka, zdroj (`prepis_app`).
- **Firm resolution (v1, deterministic):** resolve the firma by `firma_id` if given, else by **exact `ico` match**. If neither resolves, **reject the payload with a clear error (HTTP 400) and create nothing.** Fuzzy název matching and auto-creating firms are **explicitly deferred** to the future wiring phase. This gives `ingest_service` a concrete, testable contract now.
- In a later phase, the Přepis app calls `POST /api/ukony` when a žádost is finished. **No change to the Přepis app in v1.**

---

## 10. Architecture & Tech Stack

- **Stack**: Python 3.x + Flask (server-rendered Jinja templates), SQLite storage, Chart.js (vendored or CDN) for graphs, `openpyxl` for Excel, `requests` for ARES. Mirrors the existing Přepis app's stack.
- **Runs locally**: `python app.py` on a **distinct port (5051)** so it does not collide with the Přepis app (5050). Dockerizable later for NAS (out of scope for v1, not precluded).
- **File organization** (small, focused files per project coding style — repository pattern, files ≤ ~400 lines):

```
ukony_tracker/
  app.py                  # Flask app factory + blueprint registration (thin)
  config.py               # paths, port, constants
  db.py                   # SQLite connection, schema init/migrate, backup
  repositories/
    firmy_repo.py
    ukony_repo.py
    typy_repo.py
  services/
    stats_service.py      # dashboard aggregations (month/year/per-firm/per-type/outstanding)
    export_service.py     # Excel (per-firm sheets) + CSV
    ingest_service.py     # pridat_ukon(): the single write path + firm resolution (§9)
    ares_service.py       # IČO → company data (ported from prepis_app)
  routes/
    dashboard.py
    ukony.py
    firmy.py
    nastaveni.py
    export.py
    api.py                # POST /api/ukony (future hook)
  templates/              # base.html + one per screen
  static/                 # css, js (dashboard charts)
  data/                   # tracker.db + backups/  (GITIGNORED)
  scripts/
    seed.py               # seed firmy + typy + May 2026; prints reconciliation
    seed_data/            # 5.2026.xlsx  (GITIGNORED)
  tests/
    test_ukony_repo.py
    test_stats_service.py
    test_export_service.py
    test_ingest_service.py
  requirements.txt
  README.md
  CLAUDE.md
```

---

## 11. Data Safety & Validation

- **Atomic writes**: SQLite transactions for every create/update/delete.
- **Auto-backup**: before each write, copy `tracker.db` to `data/backups/` with a timestamped name; keep the last N copies (default: keep last 30; cap one backup per write burst). Mirrors the atomic-backup discipline the Přepis app applies to `firmy.xlsx`.
- **Validation at boundaries**: `datum` parseable; `celkem` numeric and ≥ 0; `zaplaceno_kc` numeric and `0 ≤ zaplaceno_kc ≤ celkem` (else reject with message); `firma_id`, `typ_kod`, `celkem` **required**; RZ/VIN free-form (no format enforcement). Friendly Czech error messages in the UI.
- **Deletes** require confirmation; no silent destructive actions.

---

## 12. Seeding / Migration

`scripts/seed.py` (idempotent — guard with a seeded flag / natural-key match so re-runs do not duplicate):

1. **Firms** — import all 9 rows from `prepis_app/firmy.xlsx` into `firmy`:
   - `nazev`, `ico`, `adresa`, `psc` mapped directly; `legacy_id` ← the `ID` column.
   - **`zkratka`**: for firms with a matching sheet in `5.2026.xlsx`, use the **sheet title** (`Albion`, `Cardion`, `Orbion`), matched to the firm by IČO/nazev (Cardion↔AUTO CARDION, Orbion↔ORBION CARS, Albion↔Albion Cars). For the other 6 firms (no May activity), default `zkratka` to the **leading distinctive token(s) of `nazev`** before the legal-form suffix (e.g. "EV trans s.r.o."→"EV trans", "MONETA Auto, s.r.o."→"MONETA", "ŠkoFIN s.r.o."→"ŠkoFIN"); all are **editable** in the Firmy screen. The col-7 sheet shortcode (`ALB`/`CARD`/`ORB`) is a *different* value and is **not** used as the zkratka.
   - **`poradi`**: active/seeded-from-sheet firms first in sheet order, then the rest alphabetically.
2. **Types** — insert default `typy_ukonu` (codes + base prices from §5.1).
3. **May 2026 úkony** — import from `scripts/seed_data/5.2026.xlsx` (sheets Albion/Cardion/Orbion) into `ukony`:
   - **Ingest only rows with a valid Datum in column A.** Skip the embedded datum-less **subtotal rows** (Albion row 49, Cardion row 120, Orbion row 69) and any stray non-úkon numeric cells (e.g. the lone value in Albion's VIN column, row 80) — otherwise they become phantom zero-date úkony and, having no type, also violate the `typ_kod NOT NULL` contract.
   - Map columns directly: `Datum→datum, RZ→rz, Úkon→typ_kod, Celkem→celkem, VIN→vin, Poznámka→poznamka`; `stav_platby='nezaplaceno'`, `zaplaceno_kc=0`, `zdroj='rucni'`.
   - **Normalize known typo** `NOVE → NOVÉ`.
   - **Unknown úkon value** (not in the seeded číselník after normalization — e.g. a one-off `TZ` used as a type): **auto-create the `typ_kod`** with `vychozi_cena = null` and **log it** to the reconciliation output, so no orphan type silently lands and no row is dropped.
4. **Reconciliation print**: after seeding, `seed.py` prints per-firm count + Celkem sum and the grand total, and asserts they match the **verified figures (datum-bearing rows only)**: **grand total 90 úkonů / 145 700 Kč**; **Cardion 59 / 84 400**, **Albion 18 / 44 500**, **Orbion 13 / 16 800**. Any mismatch fails loudly. (The per-sheet subtotal rows would sum to 291 400 = 2× the real revenue; the datum-only rule in step 3 excludes them.)

---

## 13. Testing

- **pytest** on the logic layer (the part that must be correct for a tax record):
  - repositories: CRUD + filters.
  - `stats_service`: monthly/yearly totals, per-firm, per-type, outstanding — verified against seeded May 2026 figures (§12 reconciliation numbers).
  - `export_service`: exported Excel/CSV values, payment columns, and totals-row placement match the aggregation layer.
  - `ingest_service`: create path; **firm resolution by `firma_id` and exact `ico`**; **unknown-firm payload rejected with error and nothing created** (§9); validation rejects bad input (negative celkem, zaplaceno_kc > celkem, missing typ_kod).
- Target ≥ 80% coverage on the logic layer (per project rules).

---

## 14. Design / Visual Style

- **Structure is fixed**: Layout A and the screen set in §6 do not depend on the visual reference.
- **Fallback default theme** (used so implementation is never blocked if the reference is late): system font stack (`-apple-system, system-ui, …`), light-gray canvas `#f5f5f7`, white rounded cards, a single blue accent `#0071e3`, segmented controls — i.e. the Apple-like style already prototyped.
- David will provide a **design reference** (palette/font/app); when it arrives, the theme variables are swapped to match. This is a CSS-variable retheme, not a structural change.

---

## 15. Acceptance Criteria

- Can add/edit/delete úkony per firm with price auto-fill; totals update live.
- Dashboard shows correct month/YTD KPIs, a monthly trend graph, per-firm and per-type breakdowns, and outstanding totals — numbers match the seeded May 2026 data (§12).
- Payment status + amount received recordable; outstanding computed correctly.
- Export produces a one-sheet-per-firma Excel (with `Zaplaceno`/`Zaplaceno Kč` columns and per-firm totals row) and a flat CSV, with totals matching the dashboard.
- Firms manageable with ARES lookup; all 9 seeded with non-empty `zkratka`; úkon types/prices editable.
- Data persists in SQLite with auto-backup; no data loss on normal use; `seed.py` reconciliation passes.
- `pridat_ukon()` + `POST /api/ukony` exist and are tested (firm resolution + rejection path), with the Přepis app unchanged.

---

## 16. Open Items (non-blocking, decide during build)

- Exact backup retention `N` and burst cadence — default given in §11 (last 30); tune if needed.
- Final visual theme values — pending David's reference (§14); fallback default unblocks all non-visual work.
