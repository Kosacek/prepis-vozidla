# Úkony Tracker

Lokální webová aplikace pro evidenci administrativních úkonů (přepisy, nové registrace, dovoz, vývoz…) po firmách. Nahrazuje měsíční Excel tabulku: stejný mentální model, ale s přehledovým dashboardem, sledováním plateb a exportem do .xlsx.

## Požadavky

- Python 3.10+
- Soubory (gitignorované, musí existovat lokálně):
  - `prepis_app/firmy.xlsx` — seznam 9 firem (Název, IČO, Adresa, PSČ, ID)
  - `scripts/seed_data/5.2026.xlsx` — výkazy za květen 2026 (listy Albion / Cardion / Orbion)

## Instalace

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Naplnění daty (seed)

```bash
.venv\Scripts\python.exe -m scripts.seed
```

Naseeduje 9 firem, typy úkonů a všechny úkony z května 2026. Na konci vypíše rekonciliaci: **90 úkonů / 145 700 Kč** (Cardion 59/84 400, Albion 18/44 500, Orbion 13/16 800). Pokud čísla neodpovídají, skript selže hlasitě.

Skript je idempotentní — opakované spuštění data nezdvojí.

## Spuštění

```bash
.venv\Scripts\python.exe app.py
```

Otevři `http://localhost:5051`.

## Testy

```bash
.venv\Scripts\python.exe -m pytest -q
```

Pokrytí logické vrstvy (db, repositories, services, scripts/seed) je ≥ 80 %.

## Struktura projektu

```
ukony_tracker/
  app.py            # Flask app factory + registrace blueprintů
  config.py         # cesty, port, konstanty
  db.py             # SQLite připojení, inicializace schématu, auto-backup
  repositories/     # CRUD pro firmy, úkony, typy (Repository pattern)
  services/
    stats_service.py    # agregace pro dashboard
    export_service.py   # export do Excelu a CSV
    ingest_service.py   # pridat_ukon() — jediná write-cesta
    ares_service.py     # vyhledání firmy v ARES dle IČO
  routes/           # Flask blueprinty (dashboard, ukony, firmy, nastaveni, export, api)
  templates/        # Jinja2 šablony
  static/           # CSS, JS (Chart.js grafy)
  data/             # tracker.db + backups/ — GITIGNOROVÁNO
  scripts/
    seed.py             # naplnění DB; tiskne rekonciliaci
    seed_data/          # 5.2026.xlsx — GITIGNOROVÁNO (osobní data)
  tests/            # pytest sada
  docs/             # specifikace a plán
```

## Co je gitignorováno

- `data/` — živá databáze a zálohy (osobní finanční data)
- `scripts/seed_data/` — zdrojové xlsx výkazy (osobní finanční data)
- `.coverage`, `.pytest_cache/`, `__pycache__/`
