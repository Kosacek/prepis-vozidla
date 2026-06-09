# CLAUDE.md — Úkony Tracker

Pokyny pro budoucí Claude sessions pracující s tímto projektem.

## Stack

- **Backend:** Python 3.10+ / Flask (server-rendered Jinja2 šablony)
- **Databáze:** SQLite (`data/tracker.db`)
- **Grafy:** Chart.js (dashboard)
- **Export:** openpyxl (.xlsx), Python csv (CSV)
- **ARES lookup:** requests → `ares.gov.cz` REST API

## Porty

| Aplikace | Port |
|---|---|
| Úkony Tracker (tato app) | **5051** |
| Přepis Vozidla (sourozenec) | **5050** |

Nikdy neměň port — obě aplikace běží zároveň na stejném stroji.

## Pevná pravidla

### Zdroj pravdy pro peníze

`ukony.celkem` je **jediný zdroj pravdy** pro cenu úkonu. `typy_ukonu.vychozi_cena` je pouze **editovatelný nápověd**, který předvyplní pole Cena při výběru typu — uživatel ho přepíše, když se reálná cena liší. Všechny agregace a exporty čtou `celkem`, nikdy `vychozi_cena`.

### Seedování — přeskakuj subtotal řádky

Každý list v `5.2026.xlsx` končí ručně přidaným subtotal řádkem bez data v sloupci A (Albion řádek 49, Cardion řádek 120, Orbion řádek 69). Seed musí **přeskočit jakýkoliv řádek bez platného datetime/date v sloupci A**. Pokud subtotal řádky zahrneš, celkový součet se zdvojí na 291 400 Kč místo správných 145 700 Kč — seed to odhalí díky rekonciliačnímu assertu.

### Jediná write-cesta

Veškeré zápisy nových úkonů jdou přes `ingest_service.pridat_ukon()`. Platí pro:
- UI (POST `/ukony/<firma_id>`)
- REST API (POST `/api/ukony`)

Nikdy nepiš přímo do DB mimo tuto funkci.

### Auto-backup

Auto-backup je centralizovaný v `app.before_request` — spustí se throttlovaně před každým POST/PUT/PATCH/DELETE. Neimplementuj zálohu jinde; neodstraňuj tento hook.

### Gitignorovaná data

`data/` (živá DB + zálohy) a `scripts/seed_data/` (zdrojové xlsx) jsou osobní finanční data — **nikdy je nepřidávej do gitu**.

## Budoucí integrace

Aplikace Přepis Vozidla bude v budoucí fázi posílat hotové žádosti na `POST /api/ukony`. Firma se páruje **přesnou shodou IČO** — žádný fuzzy matching, žádné auto-vytváření firem. Endpoint a `ingest_service` jsou navrženy a otestovány; Přepis app se v současnosti nemění.

## Klíčové soubory

| Soubor | Účel |
|---|---|
| `ingest_service.py` | pridat_ukon() — jediná write-cesta, derivace stav_platby |
| `stats_service.py` | agregace pro dashboard (mesicni_souhrn, rocni_trend, podle_firmy, nezaplaceno_celkem) |
| `export_service.py` | Excel (jeden list na firmu) + CSV export |
| `ares_service.py` | Lookup firmy v ARES dle IČO |
| `db.py` | Schéma, backup_db() (throttlované zálohy) |
| `scripts/seed.py` | Seed + rekonciliace; idempotentní |

## Dokumentace

- **Specifikace:** `docs/superpowers/specs/2026-06-09-ukony-tracker-design.md`
- **Implementační plán:** `docs/superpowers/plans/2026-06-09-ukony-tracker.md`
