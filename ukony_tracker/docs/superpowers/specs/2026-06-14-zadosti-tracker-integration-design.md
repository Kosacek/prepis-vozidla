# Spec — zadosti → Úkony Tracker integration

**Date:** 2026-06-14
**Status:** Approved (design), pending implementation plan
**Apps:** `prepis_app` (zadosti.spznaklic.cz) → `ukony_tracker` (evidence.spznaklic.cz)

## Goal

Every finished žádost generated in the zadosti app becomes an úkon in the Úkony
Tracker, assigned to one of the tracker's client firms (Cardion, Albion, …).
When the client firm can be identified by IČO, the úkon is created
automatically; otherwise the žádost waits in a **Příchozí** (incoming) inbox in
the tracker where the user assigns it manually.

## Current state (as mapped)

- **zadosti (`prepis_app`)** — Flask, **stateless** (no DB). Generates PDFs at
  `POST /api/generate` (`app.py` ~1054–1190); the full žádost data only exists
  in memory there, then is discarded. A žádost captures:
  - `mode`: `prevod` | `zapis` | `zmena`
  - vehicle: `registracni_znacka` (RZ), `vin`, `osvedceni_serie` (3 letters) +
    `osvedceni_cislo` (6 digits) = ORV, plus `druh`/`znacka`/etc.
  - parties, each with optional IČO: `puvodni_*` (seller/original owner) and
    `novy_*` (buyer/new owner), plus optional operators `puvodni_prov_*` /
    `novy_prov_*`. IČO is frequently blank (private persons).
- **tracker (`ukony_tracker`)** — Flask + SQLite. Firms have an `ico`. `ukony`
  has `firma_id, datum, typ_kod, celkem, rz, vin, poznamka, stav_platby,
  zaplaceno_kc, zdroj`. `POST /api/ukony` (single write path
  `ingest_service.pridat_ukon`) exists but sits behind the session login gate.
  Firm matching is **exact IČO only** (`firmy_repo.get_by_ico`), no fuzzy, no
  auto-create.

## Decisions

1. **Transport** — server-to-server `POST` from zadosti to the tracker over the
   **internal docker network** (`http://ukony-app:8090`), authenticated with a
   shared **`X-Api-Key`** header. The tracker's `/api/*` routes are exempted from
   the session gate and instead require this key. Key lives only in each app's
   NAS `.env`. *(Fallback if the two containers are not on the same docker
   network: use the public `https://evidence.spznaklic.cz` base — same key.)*
2. **Hybrid auto + inbox** — on receipt the tracker collects every non-empty IČO
   from both parties (owners + operators) and matches each against its firms:
   - **mode ∈ {prevod, zapis} AND exactly one distinct firm matched** →
     **auto-create the úkon** (goes straight to the úkon list).
   - **no match, multiple distinct firms matched, or mode = zmena** → store as a
     **pending** row in the Příchozí inbox.
3. **Inbox ("Příchozí")** — a tracker screen + nav badge with the pending count.
   Each row shows vehicle (RZ/VIN/ORV), mode, and both party names+IČO. Controls:
   firm `<select>` (pre-selected to the suggested firm if a single/partial match
   existed), type `<select>` (pre-filled prevod→PŘEVOD, zapis→NOVÉ, zmena→blank),
   price input (defaults to the chosen type's `vychozi_cena`), **Approve**
   (→ creates the úkon) and **Discard**.
4. **Field mapping (žádost → úkon)**

   | úkon field | source |
   |---|---|
   | `firma_id` | matched firm (auto) / chosen in inbox |
   | `typ_kod` | prevod→`PŘEVOD`, zapis→`NOVÉ`; zmena→chosen in inbox |
   | `celkem` | the type's `vychozi_cena` (default), editable on the úkon |
   | `datum` | **system date at žádost generation (real today)** — never the žádost's printed/post-dated form date |
   | `rz` | žádost RZ (uppercased) |
   | `vin` | **full VIN** |
   | `orv` | **new column** — `osvedceni_serie` + `osvedceni_cislo` (e.g. `ABC123456`), uppercased |
   | `poznamka` | short party context, e.g. `nový ← původní` names |
   | `zaplaceno_kc` | `0` (payment untouched) |
   | `zdroj` | `zadosti` |

5. **`datum` rule** — the work date is the day the žádost is generated (real
   today, taken from zadosti's system clock and sent in the payload). The
   žádost's on-form date is intentionally post-dated (tomorrow) for the úřad and
   must **not** be used. Inbox items pre-fill the arrival/work date (editable), so
   approving days later still records the day the work happened.
6. **ORV** — new first-class `orv` column on `ukony`: auto-filled from žádosti,
   shown in the "Tento měsíc" list and the Excel export, and an optional field on
   the manual entry form.
7. **Idempotency** — zadosti generates a `zadost_id` (uuid4) per generate and
   includes it. A repeat POST with the same `zadost_id` is ignored (guards
   against retries/double-clicks). Re-generating a žádost (new uuid) creates a new
   entry; duplicates are discarded in the inbox / deleted from the úkon list (no
   fuzzy dedup in v1).
8. **Resilience** — the push is **best-effort**: short timeout, wrapped so it
   never blocks or breaks PDF generation. On failure zadosti appends the payload
   to `failed_pushes.jsonl` under its `DATA_DIR` so nothing is silently lost.
9. **Privacy** — do **not** send rodné číslo (RČ) or addresses; only what an úkon
   needs (vehicle ids, mode, party names + IČO for matching/context).

## Out of scope (v1)

- **"Mark the whole month paid for a firm"** button — planned follow-up; payment
  stays per-úkon and untouched by the integration.
- Syncing PPD receipts, plné moci, or scanned documents.
- No new `ZMĚNA` úkon type (zmena žádosti always go to the inbox; user picks).
- Fuzzy dedup beyond the `zadost_id` idempotency key.

## Tracker changes (`ukony_tracker`)

### Schema / migration (`db.py`)
- `ALTER TABLE ukony ADD COLUMN orv TEXT` (guarded — only if the column is
  missing, so existing DBs upgrade in place on boot).
- New table `prichozi`:
  `id, zadost_id TEXT UNIQUE, received_at TEXT, datum TEXT, mode TEXT, rz TEXT,
   vin TEXT, orv TEXT, puvodni_jmeno TEXT, puvodni_ico TEXT, novy_jmeno TEXT,
   novy_ico TEXT, suggested_firma_id INTEGER, status TEXT (pending|approved|
   discarded|auto), created_ukon_id INTEGER, raw_json TEXT, created_at, updated_at`.

### Repositories / services
- `repositories/prichozi_repo.py`: `create`, `get`, `get_by_zadost_id`,
  `list_by_status`, `update_status`.
- `services/matching_service.py`: `match(conn, icos: list[str]) -> {firma_id|None,
  matched: list[firma], ambiguous: bool}` (exact IČO, distinct firms).
- `services/ingest_service.pridat_ukon`: add `orv` parameter (stored on the úkon).
- `services/ingest_service` (or a small `prichozi_service`): `intake(conn,
  payload)` — idempotency check, gather candidate IČOs, run matching, decide
  auto-create vs queue.

### Routes
- `POST /api/prichozi` (key-auth): receive payload → `intake` → return
  `{status: "auto", ukon_id}` or `{status: "pending", prichozi_id}` (or
  `{status: "duplicate"}` when `zadost_id` already seen).
- `POST /api/ukony`: keep, now also key-auth.
- `GET /prichozi`: inbox list (session-gated UI).
- `POST /prichozi/<id>/approve` (form: `firma_id, typ_kod, celkem, datum`) →
  create úkon via `ingest_service`, mark `approved`, link `created_ukon_id`.
- `POST /prichozi/<id>/discard` → mark `discarded`.

### Auth (`app.py` before_request gate, `config.py`)
- `INTEGRATION_API_KEY` env. `/api/*` paths are exempt from the session-login
  redirect but require `X-Api-Key == INTEGRATION_API_KEY` (else `401`). When the
  key is unset (local/dev), `/api/*` is open (current behavior). `/healthz`,
  `/health`, `/login`, static stay exempt as today.

### UI (Apple-consistent with existing styles)
- Nav: **Příchozí** link with a pending-count badge.
- `templates/prichozi.html`: rows with vehicle + parties + mode; firm select
  (pre-selected suggestion), type select (pre-filled by mode), price input
  (JS sets default from the chosen type), Approve / Discard.
- Entry form (`ukony_entry.html`): add optional **ORV** field; "Tento měsíc" list
  shows ORV; `export_service` adds an ORV column.

### Tests (pytest, follow existing suite)
- `matching_service`: match on either side, no match, multiple distinct →
  ambiguous, single match.
- `POST /api/prichozi`: auto-create (prevod, single match), queue (no match),
  queue (zmena even if matched), duplicate `zadost_id` ignored, missing/wrong key
  → 401, datum taken from payload (not recomputed/form date).
- approve / discard routes mark status correctly; approve respects the chosen
  firma/typ/celkem/datum.
- `orv` stored via `ingest_service`, shown in entry list, present in export.

## zadosti changes (`prepis_app`)

- New `tracker_push.py`: builds the payload `{zadost_id, datum (system today
  ISO), mode, rz, vin, orv, puvodni_jmeno, puvodni_ico, novy_jmeno, novy_ico,
  (operator icos for matching)}` and POSTs to `UKONY_API_URL + "/api/prichozi"`
  with `X-Api-Key`, short timeout. On any failure, append the payload to
  `DATA_DIR/failed_pushes.jsonl` and log; never raise into the generate flow.
- `app.py /api/generate`: after successful PDF generation, call
  `tracker_push.push(...)` (best-effort).
- New env: `UKONY_API_URL` (default `http://ukony-app:8090`), `UKONY_API_KEY`.
- Tests: payload shape; `datum` is system today, not the form date; failure path
  writes to `failed_pushes.jsonl` and does not raise.

## Deployment

- **Tracker:** add `INTEGRATION_API_KEY` to its NAS `.env`; bump `CACHEBUST`;
  rebuild. The boot-time migration adds `orv` + `prichozi` (additive, safe).
  Back up `tracker.db` before deploy.
- **zadosti:** add `UKONY_API_URL` + `UKONY_API_KEY` (same key) to its NAS
  `.env`; rebuild.
- Verify the two containers share a docker network so `ukony-app:8090` resolves;
  if not, point `UKONY_API_URL` at `https://evidence.spznaklic.cz`.
- Acceptance: generate a test žádost whose buyer IČO is a tracker firm → an úkon
  appears in the tracker; generate one with no matching IČO → it appears in
  Příchozí and can be assigned + approved.

## Risks

- **Docker network reachability** between zadosti and ukony-app (mitigated by
  public-URL fallback).
- `typ_kod` auto values (`PŘEVOD`, `NOVÉ`) must exist in `typy_ukonu` (they do per
  seed).
- Existing tracker DB must gain the `orv` column via the guarded migration.
- A wrong auto-match is possible (the matched firm might be the *other* party);
  acceptable because auto-created úkony are editable/deletable in the tracker.
