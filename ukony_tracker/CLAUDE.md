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

## Integrace s Přepis Vozidla — HOTOVO

Přepis Vozidla (zadosti.spznaklic.cz) posílá každou hotovou žádost na
**`POST /api/prichozi`** (auth `X-Api-Key`). Firma se páruje **přesnou shodou
IČO** — žádný fuzzy matching, žádné auto-vytváření firem:
- shoda IČO → buď se rovnou založí úkon, nebo se položka zařadí do **Příchozí**
  inboxu k potvrzení,
- bez shody → zůstává v Příchozí inboxu.

Druhá strana je `../prepis_app/tracker_push.py` (best-effort, nikdy neshodí
generování PDF; neúspěšné pushe → `failed_pushes.jsonl`). Klíč musí sedět s
`UKONY_API_KEY` na straně Přepisu.

**Explicitní úkon z Přepisu (2026-07-11):** když v Přepisu na poslední straně
(karta „Evidence úkonu") vybereš firmu + typ + cenu, pošlou se v payloadu jako
`firma_id` / `typ_kod` / `celkem`. `prichozi_service.intake` je pak upřednostní
před IČO-matchem a **vytvoří úkon rovnou** (jakýkoliv mód včetně `zmena`, jakákoliv
firma) — pořád přes `pridat_ukon`, pořád deduplikace přes `zadost_id`, pořád
audit řádek. Bez explicitní volby → původní auto-match. Přibyly typy **KOLA** a
**A50-X** (technické změny; seedují se idempotentně v `init_schema`). Nový
read-only `GET /api/evidence-meta` (firmy + typy + ceny, chráněný `X-Api-Key`)
plní výběr na straně Přepisu.

## Klíčové soubory

| Soubor | Účel |
|---|---|
| `ingest_service.py` | pridat_ukon() — jediná write-cesta, derivace stav_platby |
| `stats_service.py` | agregace pro dashboard (mesicni_souhrn, rocni_trend, podle_firmy, nezaplaceno_celkem) |
| `export_service.py` | Excel (jeden list na firmu) + CSV export |
| `ares_service.py` | Lookup firmy v ARES dle IČO |
| `orv_service.py` | ORV→VIN lookup (dataovozidlech.cz) pro auto-doplnění VIN v úkon formu; potřebuje `DATAOVOZIDLECH_API_KEY` v `.env` + compose (session route `GET /orv-lookup`, NE `/api/*`) |
| `db.py` | Schéma, backup_db() (throttlované zálohy) |
| `scripts/seed.py` | Seed + rekonciliace; idempotentní |

## Deploy (každá změna)

Běží jako kontejner `ukony-app` (port 8090) na QNAP NASu, `/share/Container/ukony/`.
`DEPLOY.md` popisuje prvotní zřízení (nginx, Cloudflare) — rutinní update je:

1. `python -m pytest tests/` musí projít.
2. Zvyš `ARG CACHEBUST=<datum>-<slug>` v `Dockerfile` (jinak COPY vrstvy zůstanou staré).
3. `git commit` + push (repo je VEŘEJNÉ — nikdy žádné tajné údaje).
4. Nakopíruj změněné soubory do `/share/Container/ukony/source` — přes SMB
   (`\\192.168.1.18\Container\ukony\source`) nebo
   `python ../prepis_app/scripts/nas_deploy.py puttree . /share/Container/ukony/source`
   (NAS creds přes env `NAS_USER`/`NAS_PASSWORD` — nikdy necommitovat).
5. `python ../prepis_app/scripts/nas_deploy.py run "sh /share/Container/ukony/deploy.sh"`
   — build + `up -d --force-recreate` (bez recreate zůstane běžet STARÝ kontejner!)
   + nginx reload.
6. Ověř: healthcheck `healthy`, `docker exec ukony-app cat /etc/cachebust` ukazuje
   nový slug, `/healthz` vrací ok. (Prod je Python 3.12 — sleduj start, viz gotcha
   s anotacemi.)
7. Uživateli: hard-refresh (Ctrl+Shift+R).

## Dokumentace

- **Specifikace:** `docs/superpowers/specs/2026-06-09-ukony-tracker-design.md`
- **Implementační plán:** `docs/superpowers/plans/2026-06-09-ukony-tracker.md`
