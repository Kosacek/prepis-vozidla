# Úkony Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone local web app that records vehicle administrative *úkony* per firm (replacing the manual monthly Excel), with a dashboard (monthly revenue trend, per-firm/per-type breakdowns, outstanding), payment tracking, and Excel/CSV export.

**Architecture:** Python/Flask server-rendered app over a SQLite database. A thin connection-based repository layer (`repositories/`) is wrapped by a service layer (`services/`) that holds all business logic and aggregations; Flask routes (`routes/`) are thin and call services. A single `ingest_service.pridat_ukon()` is the only write path for úkony (used by the UI and by a future-facing `POST /api/ukony`). The logic layer is pure (takes a `sqlite3.Connection`) so it is fully unit-testable without Flask.

**Tech Stack:** Python 3.x, Flask, sqlite3 (stdlib), openpyxl (export + seed read), requests (ARES), Chart.js (CDN/vendored, dashboard only), pytest.

**Spec:** `ukony_tracker/docs/superpowers/specs/2026-06-09-ukony-tracker-design.md`

---

## Conventions (read once)

- **Working directory:** all paths are relative to `prepis_vozidla_app/ukony_tracker/` unless stated. Run commands from there.
- **Windows shell:** PowerShell. Activate the venv per Task 1. Use `python -m pytest`, not bare `pytest`.
- **TDD on the logic layer:** db, repositories, services, seed, and the API endpoint are built test-first (RED → GREEN → commit). Routes/templates (HTML UI) are verified manually in the browser with explicit checklists, since fully TDD-ing server-rendered HTML adds little here.
- **Connection-based:** repository and service functions take `conn` (a `sqlite3.Connection`) as the first argument. Tests create a temp-file DB, call `db.init_schema(conn)`, and exercise functions directly. Flask supplies a per-request connection via `flask.g`.
- **Commit after every GREEN.** Conventional commits (`feat:`, `test:`, `chore:`). Attribution is disabled globally — do not add co-author trailers.
- **Czech everywhere in UI/data**; code identifiers in ASCII (`pridat_ukon`, `typ_kod`).
- **Money:** `ukony.celkem` is the source of truth. `typy_ukonu.vychozi_cena` only pre-fills the form.

---

## File Structure

```
ukony_tracker/
  app.py                  # Flask app factory + blueprint registration + g/db wiring (thin)
  config.py               # paths (DB, seed data), PORT=5051, ARES base URL, backup retention
  db.py                   # connect(path), init_schema(conn), backup_db(path), get_db()/close_db() (Flask g)
  repositories/
    __init__.py
    firmy_repo.py         # CRUD + list (ordered by poradi), get_by_ico
    typy_repo.py          # CRUD + list_active, get_by_kod, upsert
    ukony_repo.py         # create, get, update, delete, list (filters: firma/year/month/typ/stav)
  services/
    __init__.py
    ingest_service.py     # pridat_ukon(): validate + resolve firma + create (THE write path); errors
    stats_service.py      # mesicni_souhrn, rocni_trend, podle_firmy, podle_typu, nezaplaceno_celkem
    export_service.py     # export_excel(per-firm sheets+totals), export_csv
    ares_service.py       # lookup_ico() -> dict|None (ported from prepis_app)
  routes/
    __init__.py
    dashboard.py          # GET /                (Přehled)
    ukony.py              # GET/POST entry (firm-tabbed), full table, edit/delete/mark-paid
    firmy.py              # GET/POST firmy CRUD + ARES lookup endpoint
    nastaveni.py          # GET/POST typy_ukonu CRUD
    export.py             # GET /export/excel, /export/csv
    api.py                # POST /api/ukony  (future hook; calls ingest_service)
  templates/
    base.html             # layout, nav, Apple-default theme via CSS vars
    dashboard.html
    ukony_entry.html      # Layout A (firm pills, add card, month list)
    ukony_table.html
    firmy.html
    nastaveni.html
  static/
    css/app.css           # CSS variables (theme) + components
    js/dashboard.js       # Chart.js init from JSON in the page
  data/                   # tracker.db + backups/   (GITIGNORED)
  scripts/
    seed.py               # seed firmy + typy + May 2026; prints + asserts reconciliation
    seed_data/5.2026.xlsx  # (GITIGNORED, already present)
  tests/
    conftest.py           # temp-db fixture + seeded-db fixture
    test_db.py
    test_firmy_repo.py
    test_typy_repo.py
    test_ukony_repo.py
    test_ingest_service.py
    test_stats_service.py
    test_export_service.py
    test_ares_service.py
    test_seed.py
    test_api.py
  requirements.txt
  requirements-dev.txt
  README.md
  CLAUDE.md
```

---

## Phase 0 — Scaffolding

### Task 1: Project skeleton, config, venv, dependencies

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `config.py`, `app.py` (minimal), `tests/conftest.py`, `.gitignore` entries (already set at repo root for `data/` and `scripts/seed_data/`)

- [ ] **Step 1: Create `requirements.txt`**
```
flask
openpyxl
requests
```

- [ ] **Step 2: Create `requirements-dev.txt`**
```
-r requirements.txt
pytest
pytest-cov
```

- [ ] **Step 3: Create venv and install**

Run (PowerShell, from `ukony_tracker/`):
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```
Expected: installs without error. (The repo-root `.gitignore` already ignores `.venv/`, `ukony_tracker/data/`, and `ukony_tracker/scripts/seed_data/` — no gitignore edit needed.)

- [ ] **Step 3b: Create `pytest.ini`** (so imports resolve regardless of how/where pytest is invoked)
```
[pytest]
pythonpath = .
```

- [ ] **Step 4: Create `config.py`**
```python
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "tracker.db")

SEED_DIR = os.path.join(BASE_DIR, "scripts", "seed_data")
SEED_UKONY_XLSX = os.path.join(SEED_DIR, "5.2026.xlsx")
FIRMY_XLSX = os.path.abspath(os.path.join(BASE_DIR, "..", "prepis_app", "firmy.xlsx"))

PORT = 5051
ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
BACKUP_RETENTION = 30
BACKUP_MIN_INTERVAL_SEC = 300  # throttle: at most one backup per 5 min (avoids churn during batch entry)

STAV_NEZAPLACENO = "nezaplaceno"
STAV_ZAPLACENO = "zaplaceno"
STAV_CASTECNE = "castecne"
```

- [ ] **Step 5: Create minimal `app.py` with a health route**
```python
from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)
    @app.get("/health")
    def health():
        return jsonify(status="ok")
    return app

if __name__ == "__main__":
    import config
    create_app().run(host="127.0.0.1", port=config.PORT, debug=True)
```

- [ ] **Step 6: Smoke test it boots**

Run: `python -c "import app; c=app.create_app().test_client(); print(c.get('/health').json)"`
Expected: `{'status': 'ok'}`

- [ ] **Step 7: Commit**
```
git add ukony_tracker/requirements*.txt ukony_tracker/config.py ukony_tracker/app.py
git commit -m "chore: scaffold ukony_tracker (flask app, config, deps)"
```

---

## Phase 1 — Data layer

### Task 2: `db.py` — connection, schema, backup

**Files:**
- Create: `db.py`, `tests/conftest.py`, `tests/test_db.py`

- [ ] **Step 1: Write `tests/conftest.py`**
```python
import sqlite3, pytest, db

@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "t.db"
    c = db.connect(str(path))
    db.init_schema(c)
    yield c
    c.close()
```

- [ ] **Step 2: Write failing test `tests/test_db.py`**
```python
def test_schema_has_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"firmy", "typy_ukonu", "ukony"} <= names

def test_ukony_check_constraints(conn):
    conn.execute("INSERT INTO firmy(nazev,zkratka) VALUES('F','F')")
    fid = conn.execute("SELECT id FROM firmy").fetchone()["id"]
    import pytest, sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ukony(firma_id,datum,typ_kod,celkem,stav_platby,zaplaceno_kc,zdroj,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (fid, "2026-05-01", "PŘEVOD", -1, "nezaplaceno", 0, "rucni", "x", "x"))
```

- [ ] **Step 3: Run — expect FAIL** (`python -m pytest tests/test_db.py -v`) → ImportError/`connect` missing.

- [ ] **Step 4: Implement `db.py`**
```python
import os, sqlite3, shutil, glob
from datetime import datetime, timezone
from flask import g
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS firmy (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nazev TEXT NOT NULL,
  zkratka TEXT NOT NULL,
  ico TEXT,
  adresa TEXT,
  psc TEXT,
  aktivni INTEGER NOT NULL DEFAULT 1,
  poradi INTEGER NOT NULL DEFAULT 0,
  legacy_id INTEGER
);
CREATE TABLE IF NOT EXISTS typy_ukonu (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kod TEXT NOT NULL UNIQUE,
  vychozi_cena REAL,
  poradi INTEGER NOT NULL DEFAULT 0,
  aktivni INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS ukony (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  firma_id INTEGER NOT NULL REFERENCES firmy(id),
  datum TEXT NOT NULL,
  rz TEXT,
  typ_kod TEXT NOT NULL,
  celkem REAL NOT NULL,
  vin TEXT,
  poznamka TEXT,
  stav_platby TEXT NOT NULL DEFAULT 'nezaplaceno',
  zaplaceno_kc REAL NOT NULL DEFAULT 0,
  zdroj TEXT NOT NULL DEFAULT 'rucni',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (celkem >= 0),
  CHECK (zaplaceno_kc >= 0),
  CHECK (zaplaceno_kc <= celkem),
  CHECK (stav_platby IN ('nezaplaceno','zaplaceno','castecne'))
);
CREATE INDEX IF NOT EXISTS idx_ukony_firma ON ukony(firma_id);
CREATE INDEX IF NOT EXISTS idx_ukony_datum ON ukony(datum);
"""

def connect(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def backup_db(db_path=None, min_interval_sec=None):
    """Throttled, timestamped copy of the DB. Backup dir is derived from the DB
    path (so tests pointing config.DB_PATH at a tmp dir stay isolated). Skips if a
    backup was made within min_interval_sec; prunes to BACKUP_RETENTION newest."""
    import time
    db_path = db_path or config.DB_PATH
    if not os.path.exists(db_path):
        return None
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    interval = config.BACKUP_MIN_INTERVAL_SEC if min_interval_sec is None else min_interval_sec
    existing = sorted(glob.glob(os.path.join(backup_dir, "tracker_*.db")))
    if existing and interval and (time.time() - os.path.getmtime(existing[-1]) < interval):
        return None  # throttle: a recent backup already exists
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"tracker_{stamp}.db")
    shutil.copy2(db_path, dest)
    for old in sorted(glob.glob(os.path.join(backup_dir, "tracker_*.db")))[:-config.BACKUP_RETENTION]:
        os.remove(old)
    return dest

# Flask request-scoped connection
def get_db():
    if "db" not in g:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        g.db = connect(config.DB_PATH)
        init_schema(g.db)
    return g.db

def close_db(_e=None):
    c = g.pop("db", None)
    if c is not None:
        c.close()
```

- [ ] **Step 5: Run — expect PASS.** `python -m pytest tests/test_db.py -v`

- [ ] **Step 6: Commit** — `git add ukony_tracker/db.py ukony_tracker/tests/ && git commit -m "feat: sqlite schema, connection, backup"`

---

### Task 3: `repositories/typy_repo.py`

**Files:** Create `repositories/__init__.py`, `repositories/typy_repo.py`, `tests/test_typy_repo.py`

- [ ] **Step 1: Failing test `tests/test_typy_repo.py`**
```python
from repositories import typy_repo

def test_upsert_and_get(conn):
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "PŘEVOD", 1350, 1)  # update, not duplicate
    t = typy_repo.get_by_kod(conn, "PŘEVOD")
    assert t["vychozi_cena"] == 1350
    assert len(typy_repo.list_active(conn)) == 1
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `typy_repo.py`**
```python
def upsert(conn, kod, vychozi_cena=None, poradi=0, aktivni=1):
    conn.execute(
        "INSERT INTO typy_ukonu(kod,vychozi_cena,poradi,aktivni) VALUES(?,?,?,?)"
        " ON CONFLICT(kod) DO UPDATE SET vychozi_cena=excluded.vychozi_cena,"
        " poradi=excluded.poradi, aktivni=excluded.aktivni",
        (kod, vychozi_cena, poradi, aktivni))
    conn.commit()

def get_by_kod(conn, kod):
    return conn.execute("SELECT * FROM typy_ukonu WHERE kod=?", (kod,)).fetchone()

def list_active(conn):
    return conn.execute(
        "SELECT * FROM typy_ukonu WHERE aktivni=1 ORDER BY poradi, kod").fetchall()

def list_all(conn):
    return conn.execute("SELECT * FROM typy_ukonu ORDER BY poradi, kod").fetchall()
```
(`repositories/__init__.py` empty.)

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: typy_ukonu repository`

---

### Task 4: `repositories/firmy_repo.py`

**Files:** Create `repositories/firmy_repo.py`, `tests/test_firmy_repo.py`

- [ ] **Step 1: Failing test**
```python
from repositories import firmy_repo

def test_create_list_get_by_ico(conn):
    fid = firmy_repo.create(conn, nazev="AUTO CARDION s. r. o.", zkratka="Cardion",
                            ico="04156854", poradi=1)
    assert firmy_repo.get(conn, fid)["zkratka"] == "Cardion"
    assert firmy_repo.get_by_ico(conn, "04156854")["id"] == fid
    firmy_repo.create(conn, nazev="Albion Cars s.r.o.", zkratka="Albion", poradi=2)
    rows = firmy_repo.list_all(conn)
    assert [r["zkratka"] for r in rows] == ["Cardion", "Albion"]  # ordered by poradi
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `firmy_repo.py`**
```python
def create(conn, *, nazev, zkratka, ico=None, adresa=None, psc=None,
           aktivni=1, poradi=0, legacy_id=None):
    cur = conn.execute(
        "INSERT INTO firmy(nazev,zkratka,ico,adresa,psc,aktivni,poradi,legacy_id)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (nazev, zkratka, ico, adresa, psc, aktivni, poradi, legacy_id))
    conn.commit()
    return cur.lastrowid

def update(conn, fid, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE firmy SET {cols} WHERE id=?", (*fields.values(), fid))
    conn.commit()

def get(conn, fid):
    return conn.execute("SELECT * FROM firmy WHERE id=?", (fid,)).fetchone()

def get_by_ico(conn, ico):
    if not ico:
        return None
    return conn.execute("SELECT * FROM firmy WHERE ico=?", (ico,)).fetchone()

def list_all(conn, only_active=False):
    q = "SELECT * FROM firmy"
    if only_active:
        q += " WHERE aktivni=1"
    q += " ORDER BY poradi, nazev"
    return conn.execute(q).fetchall()
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: firmy repository`

---

### Task 5: `repositories/ukony_repo.py`

**Files:** Create `repositories/ukony_repo.py`, `tests/test_ukony_repo.py`

- [ ] **Step 1: Failing test** (CRUD + filters)
```python
from repositories import ukony_repo, firmy_repo

def _firma(conn): return firmy_repo.create(conn, nazev="F", zkratka="F", ico="1")

def test_create_and_filter(conn):
    fid = _firma(conn)
    ukony_repo.create(conn, firma_id=fid, datum="2026-05-04", rz="3BP3552",
                      typ_kod="PŘEVOD", celkem=1300)
    ukony_repo.create(conn, firma_id=fid, datum="2026-04-04", rz="X",
                      typ_kod="DOVOZ", celkem=2000)
    may = ukony_repo.list(conn, year=2026, month=5)
    assert len(may) == 1 and may[0]["rz"] == "3BP3552"
    assert len(ukony_repo.list(conn, firma_id=fid)) == 2
    assert len(ukony_repo.list(conn, typ_kod="DOVOZ")) == 1

def test_update_and_delete(conn):
    fid = _firma(conn)
    uid = ukony_repo.create(conn, firma_id=fid, datum="2026-05-04",
                            typ_kod="PŘEVOD", celkem=1300)
    ukony_repo.update(conn, uid, zaplaceno_kc=1300, stav_platby="zaplaceno")
    assert ukony_repo.get(conn, uid)["stav_platby"] == "zaplaceno"
    ukony_repo.delete(conn, uid)
    assert ukony_repo.get(conn, uid) is None
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `ukony_repo.py`**
```python
import db

def create(conn, *, firma_id, datum, typ_kod, celkem, rz=None, vin=None,
           poznamka=None, stav_platby="nezaplaceno", zaplaceno_kc=0, zdroj="rucni"):
    ts = db.now_iso()
    cur = conn.execute(
        "INSERT INTO ukony(firma_id,datum,rz,typ_kod,celkem,vin,poznamka,"
        "stav_platby,zaplaceno_kc,zdroj,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (firma_id, datum, rz, typ_kod, celkem, vin, poznamka,
         stav_platby, zaplaceno_kc, zdroj, ts, ts))
    conn.commit()
    return cur.lastrowid

def update(conn, uid, **fields):
    fields["updated_at"] = db.now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE ukony SET {cols} WHERE id=?", (*fields.values(), uid))
    conn.commit()

def get(conn, uid):
    return conn.execute("SELECT * FROM ukony WHERE id=?", (uid,)).fetchone()

def delete(conn, uid):
    conn.execute("DELETE FROM ukony WHERE id=?", (uid,))
    conn.commit()

def list(conn, *, firma_id=None, year=None, month=None, typ_kod=None, stav=None):
    q = ["SELECT u.*, f.zkratka AS firma_zkratka FROM ukony u JOIN firmy f ON f.id=u.firma_id"]
    where, args = [], []
    if firma_id is not None: where.append("u.firma_id=?"); args.append(firma_id)
    if typ_kod: where.append("u.typ_kod=?"); args.append(typ_kod)
    if stav: where.append("u.stav_platby=?"); args.append(stav)
    if year and month:
        where.append("substr(u.datum,1,7)=?"); args.append(f"{year:04d}-{month:02d}")
    elif year:
        where.append("substr(u.datum,1,4)=?"); args.append(f"{year:04d}")
    if where: q.append("WHERE " + " AND ".join(where))
    q.append("ORDER BY u.datum DESC, u.id DESC")
    return conn.execute(" ".join(q), args).fetchall()
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: ukony repository with filters`

---

## Phase 2 — Services

### Task 6: `services/ingest_service.py` — the single write path

**Files:** Create `services/__init__.py`, `services/ingest_service.py`, `tests/test_ingest_service.py`

- [ ] **Step 1: Failing test** (resolution + validation + payment derivation)
```python
import pytest
from services import ingest_service as ing
from services.ingest_service import UnknownFirmaError, ValidationError
from repositories import firmy_repo, ukony_repo

def _cardion(conn):
    return firmy_repo.create(conn, nazev="AUTO CARDION s. r. o.", zkratka="Cardion", ico="04156854")

def test_add_by_firma_id_derives_payment(conn):
    fid = _cardion(conn)
    uid = ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04",
                          typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=1300)
    assert ukony_repo.get(conn, uid)["stav_platby"] == "zaplaceno"

def test_resolve_by_exact_ico(conn):
    _cardion(conn)
    uid = ing.pridat_ukon(conn, ico="04156854", datum="2026-05-04",
                          typ_kod="DOVOZ", celkem=2000)
    assert ukony_repo.get(conn, uid)["stav_platby"] == "nezaplaceno"

def test_unknown_firma_rejected(conn):
    with pytest.raises(UnknownFirmaError):
        ing.pridat_ukon(conn, ico="99999999", datum="2026-05-04",
                        typ_kod="PŘEVOD", celkem=1300)

def test_validation_rejects_bad_input(conn):
    fid = _cardion(conn)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04", typ_kod="PŘEVOD", celkem=-5)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04", typ_kod="PŘEVOD",
                        celkem=1000, zaplaceno_kc=2000)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="not-a-date", typ_kod="PŘEVOD", celkem=1300)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `ingest_service.py`**
```python
from datetime import date
from repositories import firmy_repo, ukony_repo
import config

class IngestError(Exception): ...
class UnknownFirmaError(IngestError): ...
class ValidationError(IngestError): ...

def _resolve_firma(conn, firma_id, ico):
    if firma_id is not None:
        f = firmy_repo.get(conn, firma_id)
        if f: return f["id"]
        raise UnknownFirmaError(f"firma_id {firma_id} neexistuje")
    if ico:
        f = firmy_repo.get_by_ico(conn, ico)
        if f: return f["id"]
    raise UnknownFirmaError("firmu nelze určit (chybí firma_id i platné IČO)")

def _derive_stav(celkem, zaplaceno_kc):
    if zaplaceno_kc <= 0: return config.STAV_NEZAPLACENO
    if zaplaceno_kc >= celkem: return config.STAV_ZAPLACENO
    return config.STAV_CASTECNE

def pridat_ukon(conn, *, firma_id=None, ico=None, datum, typ_kod, celkem,
                rz=None, vin=None, poznamka=None, zaplaceno_kc=0, zdroj="rucni"):
    # NOTE: stav_platby is always DERIVED from zaplaceno_kc here (the single write
    # path), so it can never disagree with the amount. Routes that explicitly set a
    # status (e.g. "mark paid") go through ukony_repo.update, not this function.
    # validate
    try:
        date.fromisoformat(str(datum))
    except ValueError:
        raise ValidationError(f"neplatné datum: {datum!r}")
    if not typ_kod:
        raise ValidationError("typ úkonu je povinný")
    try:
        celkem = float(celkem); zaplaceno_kc = float(zaplaceno_kc or 0)
    except (TypeError, ValueError):
        raise ValidationError("cena musí být číslo")
    if celkem < 0:
        raise ValidationError("cena nesmí být záporná")
    if not (0 <= zaplaceno_kc <= celkem):
        raise ValidationError("zaplaceno musí být mezi 0 a celkovou cenou")

    fid = _resolve_firma(conn, firma_id, ico)
    stav = _derive_stav(celkem, zaplaceno_kc)
    return ukony_repo.create(conn, firma_id=fid, datum=str(datum), typ_kod=typ_kod,
                             celkem=celkem, rz=rz, vin=vin, poznamka=poznamka,
                             stav_platby=stav, zaplaceno_kc=zaplaceno_kc, zdroj=zdroj)
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: ingest_service.pridat_ukon (single write path)`

---

### Task 7: `services/stats_service.py` — dashboard aggregations

**Files:** Create `services/stats_service.py`, `tests/test_stats_service.py`

- [ ] **Step 1: Failing test** (uses controlled fixtures, not the seed)
```python
from services import stats_service as st
from services import ingest_service as ing
from repositories import firmy_repo

def _setup(conn):
    c = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
    a = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="2")
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-04", typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=1300)
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-05", typ_kod="DOVOZ", celkem=2000)  # unpaid
    ing.pridat_ukon(conn, firma_id=a, datum="2026-05-06", typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=500)  # partial
    return c, a

def test_month_summary(conn):
    _setup(conn)
    s = st.mesicni_souhrn(conn, 2026, 5)
    assert s["pocet"] == 3 and s["trzby"] == 4600

def test_outstanding(conn):
    _setup(conn)
    # unpaid 2000 + partial (1300-500=800) = 2800
    assert st.nezaplaceno_celkem(conn) == 2800

def test_per_firma_and_type(conn):
    _setup(conn)
    byf = {r["zkratka"]: r["trzby"] for r in st.podle_firmy(conn, 2026, 5)}
    assert byf == {"Cardion": 3300, "Albion": 1300}
    byt = {r["typ_kod"]: r["pocet"] for r in st.podle_typu(conn, 2026, 5)}
    assert byt == {"PŘEVOD": 2, "DOVOZ": 1}

def test_year_trend_has_12_months(conn):
    _setup(conn)
    trend = st.rocni_trend(conn, 2026)
    assert len(trend) == 12
    assert trend[4]["trzby"] == 4600  # index 4 = May
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `stats_service.py`**
```python
def mesicni_souhrn(conn, year, month):
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(celkem),0) s FROM ukony "
        "WHERE substr(datum,1,7)=?", (f"{year:04d}-{month:02d}",)).fetchone()
    return {"pocet": r["n"], "trzby": r["s"]}

def rocni_souhrn(conn, year):
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(celkem),0) s FROM ukony "
        "WHERE substr(datum,1,4)=?", (f"{year:04d}",)).fetchone()
    return {"pocet": r["n"], "trzby": r["s"]}

def rocni_trend(conn, year):
    rows = conn.execute(
        "SELECT substr(datum,6,2) m, COUNT(*) n, COALESCE(SUM(celkem),0) s "
        "FROM ukony WHERE substr(datum,1,4)=? GROUP BY m", (f"{year:04d}",)).fetchall()
    by = {r["m"]: (r["n"], r["s"]) for r in rows}
    out = []
    for mo in range(1, 13):
        n, s = by.get(f"{mo:02d}", (0, 0))
        out.append({"month": mo, "pocet": n, "trzby": s})
    return out

def _period_clause(year, month):
    if month:
        return "substr(datum,1,7)=?", f"{year:04d}-{month:02d}"
    return "substr(datum,1,4)=?", f"{year:04d}"

def podle_firmy(conn, year, month=None):
    cl, arg = _period_clause(year, month)
    return conn.execute(
        f"SELECT f.zkratka, COUNT(*) pocet, COALESCE(SUM(u.celkem),0) trzby "
        f"FROM ukony u JOIN firmy f ON f.id=u.firma_id WHERE {cl} "
        f"GROUP BY f.id ORDER BY trzby DESC", (arg,)).fetchall()

def podle_typu(conn, year, month=None):
    cl, arg = _period_clause(year, month)
    return conn.execute(
        f"SELECT typ_kod, COUNT(*) pocet, COALESCE(SUM(celkem),0) trzby "
        f"FROM ukony WHERE {cl} GROUP BY typ_kod ORDER BY pocet DESC", (arg,)).fetchall()

def nezaplaceno_celkem(conn):
    r = conn.execute("SELECT COALESCE(SUM(celkem - zaplaceno_kc),0) d FROM ukony").fetchone()
    return r["d"]
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: stats_service aggregations`

---

### Task 8: `services/ares_service.py` — IČO lookup

**Files:** Create `services/ares_service.py`, `tests/test_ares_service.py`. Reference `prepis_app/app.py` for the existing ARES call shape.

- [ ] **Step 1: Failing test** (mock `requests`)
```python
from unittest.mock import patch, MagicMock
from services import ares_service

def test_lookup_parses_ares():
    payload = {"obchodniJmeno": "AUTO CARDION s. r. o.",
               "sidlo": {"nazevUlice": "Heršpická", "cisloDomovni": 788,
                          "cisloOrientacni": 9, "nazevObce": "Brno", "psc": "63900"}}
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=200, json=lambda: payload)
        out = ares_service.lookup_ico("04156854")
    assert out["nazev"] == "AUTO CARDION s. r. o."
    assert out["psc"] == "63900"
    assert "Brno" in out["adresa"]

def test_lookup_not_found_returns_none():
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=404, json=lambda: {})
        assert ares_service.lookup_ico("00000000") is None

def test_lookup_pads_leading_zero_ico():
    # CARDION is 04156854; typing "4156854" (7 digits) must still hit the padded URL
    with patch("services.ares_service.requests.get") as g:
        g.return_value = MagicMock(status_code=200, json=lambda: {"obchodniJmeno": "X", "sidlo": {}})
        ares_service.lookup_ico("4156854")
        assert "04156854" in g.call_args[0][0]  # first positional arg = URL
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `ares_service.py`** (port the parsing from `prepis_app/app.py`; confirm field names there)
```python
import requests
import config

def lookup_ico(ico):
    digits = "".join(c for c in (ico or "") if c.isdigit())[:8]
    if not digits:
        return None
    ico = digits.zfill(8)  # ARES needs the full 8-digit, zero-padded IČO
    try:
        r = requests.get(config.ARES_URL.format(ico=ico), timeout=8,
                         headers={"Accept": "application/json"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    d = r.json()
    s = d.get("sidlo", {}) or {}
    ulice = s.get("nazevUlice") or s.get("nazevObce", "")
    cd = s.get("cisloDomovni"); co = s.get("cisloOrientacni")
    cislo = f"{cd}/{co}" if cd and co else (str(cd) if cd else "")
    adresa = " ".join(p for p in [ulice, cislo] if p).strip()
    if s.get("nazevObce") and s.get("nazevObce") not in adresa:
        adresa = f"{adresa}, {s['nazevObce']}".strip(", ")
    return {"nazev": d.get("obchodniJmeno", ""), "adresa": adresa, "psc": str(s.get("psc", "") or "")}
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: ARES lookup service`

---

### Task 9: `services/export_service.py` — Excel + CSV

**Files:** Create `services/export_service.py`, `tests/test_export_service.py`

- [ ] **Step 1: Failing test** (assert per-firm sheet + totals + payment cols)
```python
import io, openpyxl
from services import export_service as ex
from services import ingest_service as ing
from repositories import firmy_repo

def _data(conn):
    c = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-04", typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=1300)
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-05", typ_kod="DOVOZ", celkem=2000)

def test_excel_has_firm_sheet_with_total(conn):
    _data(conn)
    wb = openpyxl.load_workbook(io.BytesIO(ex.export_excel(conn, 2026, 5)))
    assert "Cardion" in wb.sheetnames
    ws = wb["Cardion"]
    header = [c.value for c in ws[1]]
    assert header[:6] == ["Datum","RZ","Úkon","Celkem","VIN","Poznámka"]
    assert "Zaplaceno" in header and "Zaplaceno Kč" in header
    # the LAST row is the totals row: a CELKEM label with the count + the period sum
    celkem_col = header.index("Celkem") + 1
    last = ws.max_row
    assert ws.cell(last, celkem_col).value == 3300
    label = str(ws.cell(last, 1).value)
    assert "CELKEM" in label and "2" in label  # "CELKEM (2 úkonů)"

def test_csv_flat(conn):
    _data(conn)
    csv = ex.export_csv(conn, "2026-05-01", "2026-05-31")
    assert "firma" in csv.splitlines()[0]
    assert csv.count("\n") >= 3  # header + 2 rows
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `export_service.py`**
```python
import io, csv as csvmod
import openpyxl
from repositories import firmy_repo, ukony_repo

HEAD = ["Datum", "RZ", "Úkon", "Celkem", "VIN", "Poznámka", "Zaplaceno", "Zaplaceno Kč"]

def export_excel(conn, year, month=None):
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    for f in firmy_repo.list_all(conn):
        rows = ukony_repo.list(conn, firma_id=f["id"], year=year, month=month)
        if not rows:
            continue
        ws = wb.create_sheet(title=(f["zkratka"] or f["nazev"])[:31])
        ws.append(HEAD)
        total = 0
        for u in sorted(rows, key=lambda r: r["datum"]):
            ws.append([u["datum"], u["rz"], u["typ_kod"], u["celkem"], u["vin"],
                       u["poznamka"], u["stav_platby"], u["zaplaceno_kc"]])
            total += u["celkem"]
        ws.append([f"CELKEM ({len(rows)} úkonů)", "", "", total, "", "", "", ""])
    if not wb.sheetnames:
        wb.create_sheet(title="Prázdné")
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

def export_csv(conn, date_from, date_to):
    rows = conn.execute(
        "SELECT u.datum, f.zkratka firma, u.rz, u.typ_kod, u.celkem, u.vin, "
        "u.poznamka, u.stav_platby, u.zaplaceno_kc FROM ukony u "
        "JOIN firmy f ON f.id=u.firma_id WHERE u.datum BETWEEN ? AND ? "
        "ORDER BY u.datum", (date_from, date_to)).fetchall()
    buf = io.StringIO()
    w = csvmod.writer(buf)
    w.writerow(["datum","firma","rz","typ","celkem","vin","poznamka","stav_platby","zaplaceno_kc"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    return buf.getvalue()
```

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: Excel/CSV export service`

---

## Phase 3 — Seeding

### Task 10: `scripts/seed.py` — firms, types, May 2026, reconciliation

**Files:** Create `scripts/seed.py`, `tests/test_seed.py`. Depends on `scripts/seed_data/5.2026.xlsx` and `prepis_app/firmy.xlsx` being present (§4.1 of spec).

- [ ] **Step 1: Failing test** (seed a temp DB, assert reconciliation)
```python
import db
from scripts import seed
from services import stats_service as st
from repositories import firmy_repo

def test_seed_reconciles_may(conn):
    seed.seed_all(conn)
    assert len(firmy_repo.list_all(conn)) == 9
    assert all(f["zkratka"] for f in firmy_repo.list_all(conn))  # non-empty
    s = st.mesicni_souhrn(conn, 2026, 5)
    assert s["pocet"] == 90 and s["trzby"] == 145700
    byf = {r["zkratka"]: (r["pocet"], r["trzby"]) for r in st.podle_firmy(conn, 2026, 5)}
    assert byf["Cardion"] == (59, 84400)
    assert byf["Albion"] == (18, 44500)
    assert byf["Orbion"] == (13, 16800)

def test_seed_idempotent(conn):
    seed.seed_all(conn); seed.seed_all(conn)
    assert st.mesicni_souhrn(conn, 2026, 5)["pocet"] == 90  # not doubled
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `scripts/seed.py`** (datum-only rule; skip subtotal/junk rows; NOVE→NOVÉ; unknown-type auto-create; zkratka derivation; reconcile)
```python
import datetime
import openpyxl
import config
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ingest_service as ing

DEFAULT_TYPY = [("PŘEVOD",1300),("NOVÉ",1300),("DOVOZ",2000),
                ("VÝVOZ",1000),("ORV",1000),("3RZ",1200)]
SHEET_ZKRATKA = {"Albion":"Albion","Cardion":"Cardion","Orbion":"Orbion"}
# sheet title -> matching firma by IČO (verified)
SHEET_ICO = {"Albion":"04168313","Cardion":"04156854","Orbion":"21231800"}
EXPECT = {"Cardion":(59,84400),"Albion":(18,44500),"Orbion":(13,16800)}

def _zkratka_from_nazev(nazev):
    # leading tokens before legal-form suffix
    suffixes = ("s.r.o.","s. r. o.","a.s.","spol.","s r.o.")
    out = nazev
    for suf in suffixes:
        i = out.lower().find(suf.lower())
        if i > 0:
            out = out[:i]; break
    return out.strip(" ,") or nazev

def seed_firmy(conn):
    if firmy_repo.list_all(conn):
        return
    wb = openpyxl.load_workbook(config.FIRMY_XLSX, read_only=True, data_only=True)
    ws = wb.active
    ico_to_sheet = {v: k for k, v in SHEET_ICO.items()}
    rows = [r for r in ws.iter_rows(values_only=True)][1:]
    ordered = sorted(
        [r for r in rows if r and r[0]],
        key=lambda r: (str(r[1]) not in ico_to_sheet, str(r[0]).lower()))
    for i, r in enumerate(ordered, 1):
        nazev, ico, adresa, psc = r[0], str(r[1]) if r[1] else None, r[2], (str(r[3]) if r[3] else None)
        legacy = r[4] if len(r) > 4 else None
        sheet = ico_to_sheet.get(ico)
        zkratka = SHEET_ZKRATKA.get(sheet) or _zkratka_from_nazev(nazev)
        firmy_repo.create(conn, nazev=nazev, zkratka=zkratka, ico=ico, adresa=adresa,
                          psc=psc, poradi=i, legacy_id=int(legacy) if legacy else None)

def seed_typy(conn):
    for i, (kod, cena) in enumerate(DEFAULT_TYPY, 1):
        typy_repo.upsert(conn, kod, cena, i)

def _norm_typ(v):
    v = str(v).strip()
    return "NOVÉ" if v == "NOVE" else v

def _vin(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # avoid '412282.0' from float cells
    return str(v)

def seed_ukony(conn):
    if ukony_repo.list(conn, year=2026, month=5):
        return
    wb = openpyxl.load_workbook(config.SEED_UKONY_XLSX, read_only=True, data_only=True)
    known = {t["kod"] for t in typy_repo.list_all(conn)}
    for ws in wb.worksheets:
        ico = SHEET_ICO.get(ws.title)
        for r in [x for x in ws.iter_rows(values_only=True)][1:]:
            datum = r[0] if r else None
            if not isinstance(datum, (datetime.datetime, datetime.date)):
                continue  # skip subtotal/junk rows (datum-only rule)
            typ = _norm_typ(r[2])
            if typ not in known:
                typy_repo.upsert(conn, typ, None, 99); known.add(typ)  # auto-create, log
                print(f"[seed] auto-created unknown typ_kod: {typ}")
            ing.pridat_ukon(conn, ico=ico, datum=datum.date().isoformat(), typ_kod=typ,
                            celkem=r[3], rz=(str(r[1]) if r[1] is not None else None),
                            vin=_vin(r[4]), poznamka=r[5] if len(r) > 5 else None)

def seed_all(conn):
    seed_firmy(conn); seed_typy(conn); seed_ukony(conn)
    _reconcile(conn)

def _reconcile(conn):
    from services import stats_service as st
    s = st.mesicni_souhrn(conn, 2026, 5)
    byf = {r["zkratka"]: (r["pocet"], r["trzby"]) for r in st.podle_firmy(conn, 2026, 5)}
    print(f"[seed] May 2026: {s['pocet']} úkonů / {int(s['trzby'])} Kč")
    for k, v in EXPECT.items():
        print(f"   {k}: {byf.get(k)} (expected {v})")
    assert s["pocet"] == 90 and s["trzby"] == 145700, "GRAND mismatch — check skip rules"
    for k, v in EXPECT.items():
        assert byf.get(k) == v, f"{k} mismatch: {byf.get(k)} != {v}"

if __name__ == "__main__":
    import db
    c = db.connect(config.DB_PATH); db.init_schema(c); seed_all(c)
```
> Note: import resolution is handled by the `pytest.ini` `pythonpath = .` from Task 1 (so `import db`, `from repositories import ...`, `from scripts import seed`, `import app` all resolve from `ukony_tracker/`). Create an empty `scripts/__init__.py` in this task so `from scripts import seed` works.

- [ ] **Step 4: Run — expect PASS.** `python -m pytest tests/test_seed.py -v`
- [ ] **Step 5: Run the seeder for real** `python -m scripts.seed` → prints `90 úkonů / 145700 Kč` and per-firm lines, no assertion error.
- [ ] **Step 6: Commit** — `feat: seed script (firms, types, May 2026) with reconciliation`

---

## Phase 4 — Routes & UI

> UI tasks: build the route + template, then **verify in the browser** (run `python app.py`, open `http://localhost:5051`). Each task lists a manual checklist. Wire `db.get_db`/`close_db` into the app factory first (Task 11).

### Task 11: App factory wiring + base template + theme

**Files:** Modify `app.py`; Create `templates/base.html`, `static/css/app.css`, `routes/__init__.py`

- [ ] **Step 1:** Expand `create_app()` to register `db.close_db` on teardown, register blueprints (each later route task adds its own `app.register_blueprint(...)` line here as it creates that blueprint — Task 18 explicitly does this for the api blueprint), set `app.config` from `config.py`, and add a `@app.context_processor` exposing the firm list + active types for nav.
- [ ] **Step 1b — CENTRALIZED AUTO-BACKUP (single chokepoint, so no route can forget):** add a `@app.before_request` hook that, for any mutating method, takes a throttled backup before the write reaches the DB:
```python
@app.before_request
def _auto_backup():
    from flask import request
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        db.backup_db()  # throttled (config.BACKUP_MIN_INTERVAL_SEC); protects every create/edit/delete
```
This covers the entry-screen create (Task 12), table edit/delete/mark-paid (Task 13), firmy/typy changes, and `POST /api/ukony` (Task 18) — all of them — satisfying spec §11/§15 "no data loss" without per-route backup calls.
- [ ] **Step 2:** `base.html` — top nav (Přehled · Úkony · Firmy · Nastavení · Export), `{% block content %}`, link `app.css`. Theme via CSS variables (the spec §14 Apple default: `--bg:#f5f5f7; --card:#fff; --accent:#0071e3; --ink:#1d1d1f; --line:#e5e5ea;` system font).
- [ ] **Step 3:** `app.css` — implement the prototyped Apple style (pills, segmented control, cards, list, tables). Keep all colors/fonts in `:root` vars so a later reskin to David's reference is a one-file change.
- [ ] **Step 4: Verify** `python app.py` → `/health` still ok; base nav renders on a placeholder route.
- [ ] **Step 5: Commit** — `feat: app factory, base template, Apple-default theme`

### Task 12: Entry screen (Layout A) — the primary screen

**Files:** Create `routes/ukony.py`, `templates/ukony_entry.html`

- [ ] **Step 1:** `GET /ukony` and `GET /ukony/<firma_id>?month=YYYY-MM` — render Layout A: firm pills (from `firmy_repo.list_all`), the "Nový úkon" card (date defaults today; segmented `typy_repo.list_active`; `vychozi_cena` injected as data attributes for JS auto-fill), the month list (`ukony_repo.list(firma_id, year, month)`) below a divider, and the firm's running total (`stats_service` or sum of the list).
- [ ] **Step 2:** `POST /ukony/<firma_id>` — call `ingest_service.pridat_ukon(get_db(), firma_id=..., ...)`; on `ValidationError` re-render with a Czech flash message; on success redirect back (PRG pattern). Small JS: picking a type fills the Cena field from its `vychozi_cena`; chips append `TZ`/`PM`/`RZ` to poznámka; after add, focus returns to RZ.
- [ ] **Step 3: Verify in browser:** select Cardion → add a PŘEVOD (Cena auto-fills 1300) → row appears in month list, total updates; add with empty type blocked; switch firm tab works; `+ firma` links to Firmy.
- [ ] **Step 4: Commit** — `feat: úkony entry screen (Layout A)`

### Task 13: Full úkony table — filter / edit / delete / mark-paid

**Files:** Modify `routes/ukony.py`; Create `templates/ukony_table.html`

- [ ] **Step 1:** `GET /ukony/vse` with query filters (firma, month, typ, stav) → `ukony_repo.list(...)`.
- [ ] **Step 2:** `POST /ukony/<id>/upravit` (edit fields), `POST /ukony/<id>/smazat` (confirm dialog in UI), `POST /ukony/<id>/zaplaceno` (set `zaplaceno_kc=celkem, stav='zaplaceno'`) and a partial-amount form. All via `ukony_repo.update/delete` (auto-backup is handled centrally by the Task 11 `before_request` hook — no per-route backup call needed).
- [ ] **Step 3: Verify:** filter by firma/month; edit a price; mark one paid (outstanding drops); delete asks to confirm.
- [ ] **Step 4: Commit** — `feat: úkony table (filter/edit/delete/mark-paid)`

### Task 14: Dashboard (Přehled) + Chart.js

**Files:** Create `routes/dashboard.py`, `templates/dashboard.html`, `static/js/dashboard.js`

- [ ] **Step 1:** `GET /` — gather `mesicni_souhrn` (current month), `rocni_souhrn` (YTD), `nezaplaceno_celkem`, `rocni_trend(year)`, `podle_firmy`, `podle_typu`. Pass trend/breakdown data as JSON in the template.
- [ ] **Step 2:** `dashboard.html` — 4 KPI cards (incl. outstanding), trend `<canvas>`, per-type + per-firma panels, recent list. `dashboard.js` reads the JSON and renders Chart.js bar (trend, Kč↔count toggle) + breakdowns. Chart.js via CDN `<script>` in base.
- [ ] **Step 3: Verify:** with seeded data, May bar shows 145 700 / 90; KPIs correct; outstanding matches; per-firma Cardion>Albion>Orbion.
- [ ] **Step 4: Commit** — `feat: dashboard with monthly trend + breakdowns`

### Task 15: Firmy management + ARES lookup

**Files:** Create `routes/firmy.py`, `templates/firmy.html`

- [ ] **Step 1:** `GET /firmy` list; `POST /firmy` create / `POST /firmy/<id>` update (nazev, zkratka, ico, adresa, psc, aktivni, poradi); `GET /firmy/ares?ico=` → JSON from `ares_service.lookup_ico` for the "fetch from IČO" button.
- [ ] **Step 2: Verify:** add a firm by IČO (ARES fills name/adresa/psc); edit zkratka; toggle aktivni hides it from entry pills.
- [ ] **Step 3: Commit** — `feat: firmy management with ARES lookup`

### Task 16: Nastavení — typy_ukonu

**Files:** Create `routes/nastaveni.py`, `templates/nastaveni.html`

- [ ] **Step 1:** `GET /nastaveni` list types; `POST` to add/edit kod + vychozi_cena + poradi + aktivni (via `typy_repo.upsert`).
- [ ] **Step 2: Verify:** change DOVOZ default to 2100 → entry screen auto-fills 2100 for new DOVOZ.
- [ ] **Step 3: Commit** — `feat: úkon type/price-list settings`

### Task 17: Export routes

**Files:** Create `routes/export.py`

- [ ] **Step 1:** `GET /export/excel?year=&month=` → `send_file` bytes from `export_service.export_excel` with `Content-Disposition` (e.g. `ukony_2026-05.xlsx`); `GET /export/csv?from=&to=` → CSV download.
- [ ] **Step 2: Verify:** download May Excel → **one sheet per firm that has úkony in the period** (regardless of `aktivni`, so the export's grand total provably equals the dashboard's all-firms total — never under-reports an inactivated firm's income), columns + Zaplaceno cols + a CELKEM row; totals equal dashboard.
- [ ] **Step 3: Commit** — `feat: Excel/CSV export routes`

### Task 18: `POST /api/ukony` (future hook) — test-first

**Files:** Create `routes/api.py`, `tests/test_api.py`

- [ ] **Step 1: Failing test** (uses Flask test client against a temp DB)
```python
import json, pytest, app as appmod, db, config

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path/"t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app(); a.testing = True
    with a.test_client() as c:
        with a.app_context():
            from repositories import firmy_repo
            firmy_repo.create(db.get_db(), nazev="Cardion", zkratka="Cardion", ico="04156854")
        yield c

def test_api_creates_by_ico(client):
    r = client.post("/api/ukony", json={"ico":"04156854","datum":"2026-05-04",
                    "typ_kod":"PŘEVOD","celkem":1300,"zdroj":"prepis_app"})
    assert r.status_code == 201

def test_api_unknown_firma_400(client):
    r = client.post("/api/ukony", json={"ico":"99999999","datum":"2026-05-04",
                    "typ_kod":"PŘEVOD","celkem":1300})
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `routes/api.py`**
```python
from flask import Blueprint, request, jsonify
import db
from services.ingest_service import pridat_ukon, UnknownFirmaError, ValidationError

bp = Blueprint("api", __name__)

@bp.post("/api/ukony")
def create_ukon():
    p = request.get_json(silent=True) or {}
    try:
        uid = pridat_ukon(db.get_db(), firma_id=p.get("firma_id"), ico=p.get("ico"),
                          datum=p.get("datum"), typ_kod=p.get("typ_kod"),
                          celkem=p.get("celkem"), rz=p.get("rz"), vin=p.get("vin"),
                          poznamka=p.get("poznamka"), zaplaceno_kc=p.get("zaplaceno_kc", 0),
                          zdroj=p.get("zdroj", "prepis_app"))
        return jsonify(id=uid), 201
    except UnknownFirmaError as e:
        return jsonify(error=str(e)), 400
    except ValidationError as e:
        return jsonify(error=str(e)), 400
```
Register the blueprint in `app.py`.

- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `feat: POST /api/ukony ingestion endpoint (future hook)`

---

## Phase 5 — Verification & docs

### Task 19: Coverage gate + full suite

- [ ] **Step 1:** Run `python -m pytest --cov=. --cov-report=term-missing`. Confirm the logic layer (db, repositories, services, scripts) is ≥ 80%.
- [ ] **Step 2:** Add tests for any uncovered logic branch (e.g. `_zkratka_from_nazev`, partial-payment derivation).
- [ ] **Step 3: Commit** — `test: raise logic-layer coverage to 80%+`

### Task 20: README, CLAUDE.md, run check

- [ ] **Step 1:** `README.md` (Czech quick-start: venv, install, `python -m scripts.seed`, `python app.py`, open `:5051`).
- [ ] **Step 2:** `CLAUDE.md` (project instructions: stack, ports 5050/5051, money-source-of-truth rule, datum-only seed rule, gitignored data dirs, link the spec).
- [ ] **Step 3: Full manual pass** against spec §15 Acceptance Criteria; tick each.
- [ ] **Step 4: Commit** — `docs: README + CLAUDE.md for ukony_tracker`

---

## Done = spec §15 satisfied

Add/edit/delete úkony with auto-fill; dashboard month/YTD/trend/per-firm/per-type/outstanding correct against seeded May (90/145 700); payment status + amount; Excel(per-firma+totals)/CSV export matching the dashboard; firmy + ARES; types/prices editable; SQLite + auto-backup; `pridat_ukon()` + tested `POST /api/ukony` with the Přepis app unchanged.
