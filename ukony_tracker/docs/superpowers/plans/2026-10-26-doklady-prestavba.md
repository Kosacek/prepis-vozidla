# Přestavba Dokladů (2.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doklady get fixed-slot rows like Úkony, an accordion with their úkony, smart multi-car
linking, a firm filter with live search, an orange "Zaplatit" on úkony with a doklad, "Nový
doklad" issued through žádosti, and a working month picker on iPhone.

**Architecture:** One pure-ish service `services/ppd_links.py` computes doklad↔úkon links per
request (explicit `ppd_ukony` table first, then zadost_id, then RZ/VIN tokens within ±14 days)
and is cached on `flask.g`; a Jinja global exposes `ukon_doklady(uid)` to `_stav_slot.html`.
The Doklady page renders all doklady server-side and filters them client-side like Úkony.
"Nový doklad" posts to evidence, which calls žádosti `POST /api/ppd/vystavit`.

**Tech Stack:** Flask + Jinja + SQLite, vanilla JS, pytest, node:test.

Spec: `docs/superpowers/specs/2026-10-26-doklady-prestavba-design.md`.

---

### Task 1: `ppd_ukony` table + linking service

**Files:**
- Modify: `db.py` (schema: `ppd_ukony(ppd_cislo INTEGER, ukon_id INTEGER, PRIMARY KEY(ppd_cislo, ukon_id))`)
- Create: `services/ppd_links.py`
- Test: `tests/test_ppd_links.py`

- [ ] Tests first: token split (`, ; \n`, spaces, case); ±14-day window; nearest date wins;
  date tie → úkon whose `celkem == castka`, else all tied; explicit `ppd_ukony` rows win and
  ignore the window; zadost_id → `prichozi.created_ukon_id`; deleted doklady ignored;
  `missing` lists tokens with no úkon; `firma_id` = majority firm of linked úkony, else
  `firmy.ico == prijato_ico`, else None; `ukon_doklady` reverse map sorted by číslo.
- [ ] Run → FAIL. Implement `compute(conn) -> Links` (dataclass: `by_doklad`, `missing`,
  `firma`, `by_ukon`) with one SQL query for candidate úkony; `for_request()` caches on `g`.
- [ ] Run → PASS. Commit.

### Task 2: Doklady page

**Files:**
- Modify: `routes/ppd.py` (`doklady()` → all doklady incl. deleted, links, úkony rows by id, firmy)
- Modify: `repositories/ukony_repo.py` (`list_by_ids`)
- Create: `templates/_doklad_item.html`
- Rewrite: `templates/doklady.html`
- Create: `static/js/doklady.js`, CSS in `static/css/app.css` (`.doklad-*`)
- Test: `tests/test_ppd.py` (page tests)

- [ ] Tests: firm select lists active firms; every doklad has `data-firma`, `data-mesic`,
  `data-search`, `data-smazano`, `data-kc`; deleted hidden by default; accordion button has
  `aria-expanded="false"` and `aria-controls`; doklad 179-like row renders its 5 úkony via
  `_ukony_item.html`; missing car shows `.doklad-missing`; legacy `?q=`/`?mesic=` prefill inputs.
- [ ] Implement; live filter JS (search fold + firm + month + platné/smazané + count/sum).
- [ ] Desktop + 390 px screenshots in preview on a backup copy. Commit.

### Task 3: Orange "Zaplatit"

**Files:** `app.py` (Jinja global), `templates/_stav_slot.html`, `static/css/app.css`
- [ ] Tests: unpaid úkon with doklad → `pay-doklad` + "č. N" in title/label; paid or without
  doklad → unchanged; `mark_paid` AJAX unpay re-renders orange.
- [ ] Implement, run, commit.

### Task 4: iPhone month picker

**Files:** `static/css/app.css`, `templates/doklady.html`, `ukony_table.html`, `ukony_entry.html`
- [ ] Fixed `min-height`/`min-width`, `::-webkit-date-and-time-value` rule, "Všechny měsíce"
  overlay label when empty (`.month-wrap[data-empty]`). Test: label present when value empty.
- [ ] Commit.

### Task 5: Nový doklad

**Files:** Create `services/doklad_issue.py`, `templates/_doklad_new_modal.html`,
`static/js/doklad_new.js`; modify `routes/ppd.py`, `config.py` (`ZADOSTI_API_URL`).
- [ ] Tests (mock `requests.post`): `GET /doklady/novy/ukony?firma=` lists unpaid úkony without
  doklad (90 days); `POST /doklady/novy` validates (firm active, 1–30 úkony of that firm,
  castka int > 0); sends contract body + `X-Api-Key`; on 201 upserts doklad + `ppd_ukony`
  rows and returns print URL; 404/timeout/5xx → error JSON, nothing saved.
- [ ] Implement, commit.

### Task 6: Release 2.5 + deploy

**Files:** `releases.py`, `templates/demos/v2_5.html`, `tests/test_whats_new.py` (if it pins version)
- [ ] Release on top, demo (179 expands → 5 rows, one orange). Full suite + node tests.
- [ ] Bump CACHEBUST + asset `?v=`, commit, push, deploy, verify healthy, screenshot popup
  375 px light (app is light-only).
