import os
import sqlite3
import shutil
import glob
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


def connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def backup_db(db_path: str | None = None, min_interval_sec: int | None = None) -> str | None:
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
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        g.db = connect(config.DB_PATH)
        init_schema(g.db)
    return g.db


def close_db(_e: Exception | None = None) -> None:
    c = g.pop("db", None)
    if c is not None:
        c.close()
