"""Background job: read incoming MONETA payments and settle fakturas.

`run_once(conn)` never raises. `start_background()` starts ONE daemon thread
(only when a token is set) guarded by an OS file lock, so only one gunicorn
worker polls.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import config
import db
from services import faktura_platby, moneta_client, moneta_matcher

log = logging.getLogger("moneta")
_lock_handle = None  # kept open for the life of the process


# ------------------------------------------------------------------ state

def get_stav(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM moneta_stav")}


def _set_stav(conn, **values) -> None:
    with conn:
        for k, v in values.items():
            conn.execute("INSERT INTO moneta_stav(key, value) VALUES(?, ?)"
                         " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def _since(stav: dict, now: datetime) -> str:
    floor = now - timedelta(days=30)
    try:
        since = datetime.fromisoformat(stav["last_ok"]) - timedelta(days=3)
    except (KeyError, ValueError):
        return floor.date().isoformat()
    return max(since, floor).date().isoformat()


# -------------------------------------------------------------------- job

def _faktury(conn):
    open_ = conn.execute("SELECT cislo, castka, vozidlo FROM ppd WHERE druh='faktura'"
                         " AND smazano=0 AND zaplaceno_dne IS NULL").fetchall()
    paid = [r["cislo"] for r in conn.execute(
        "SELECT cislo FROM ppd WHERE druh='faktura' AND smazano=0 AND zaplaceno_dne IS NOT NULL")]
    return open_, paid


NO_MATCH = "žádná odpovídající faktura"


def _stav(p, cislo, duvod) -> str:
    """Unrelated credits (rent, refunds…) are kept for dedupe but never listed:
    only a payment that looks meant for a faktura (VS shaped YYYYNNNN, or a
    reason pointing at one) needs a human."""
    if cislo:
        return "sparovano"
    faktura_vs = len(p.vs) == 8 and p.vs.isdigit() and p.vs.startswith("20")
    return "nesparovano" if (duvod != NO_MATCH or faktura_vs) else "ignorovano"


def _store(conn, p, cislo, duvod) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO moneta_platby(tx_id, datum, castka, vs, zprava, protiucet,"
            " faktura_cislo, stav, duvod, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (p.id, p.datum, float(p.castka), p.vs, p.zprava, p.protiucet, cislo,
             _stav(p, cislo, duvod), duvod or None, db.now_iso()))


def run_once(conn, fetch=None, now=None) -> None:
    """One poll. `fetch(since_date) -> list[Platba]` is injectable for tests."""
    now = now or datetime.now(timezone.utc)
    try:
        stav = get_stav(conn)
        _set_stav(conn, last_run=now.isoformat(timespec="seconds"))
        platby = (fetch or moneta_client.fetch_incoming)(_since(stav, now))
        known = {r["tx_id"] for r in conn.execute("SELECT tx_id FROM moneta_platby")}
        nove = [p for p in platby if p.id not in known]
        nove = list({p.id: p for p in nove}.values())
        open_, paid = _faktury(conn)
        shody, nesparene = moneta_matcher.sparuj(nove, open_, paid)
        for p, cislo in shody:
            try:
                faktura_platby.oznac_fakturu_zaplacenou(cislo, p.datum, conn)
                _store(conn, p, cislo, "")
            except Exception:
                log.exception("moneta: settling faktura %s failed", cislo)
                _store(conn, p, None, f"chyba při označení faktury č. {cislo}")
        for p, duvod in nesparene:
            _store(conn, p, None, duvod)
        _set_stav(conn, last_ok=now.isoformat(timespec="seconds"), last_error="", auth_failed="0")
    except moneta_client.MonetaAuthError as e:
        log.warning("moneta: auth failed: %s", e)
        _safe_state(conn, auth_failed="1", last_error=str(e))
    except Exception as e:  # never raise into the app
        log.exception("moneta: poll failed")
        _safe_state(conn, last_error=f"{type(e).__name__}: {e}"[:300])


def _safe_state(conn, **values) -> None:
    try:
        _set_stav(conn, **values)
    except Exception:
        log.exception("moneta: cannot store state")


# ------------------------------------------------------------- scheduling

def _acquire_lock() -> bool:
    """Exclusive non-blocking lock so one gunicorn worker polls. No-op (True) without fcntl."""
    global _lock_handle
    try:
        import fcntl
    except ImportError:
        return True
    try:
        import os
        os.makedirs(config.DATA_DIR, exist_ok=True)
        fh = open(os.path.join(config.DATA_DIR, "moneta.lock"), "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _lock_handle = fh
    return True


def _loop(stop: threading.Event, interval_s: float, run, first_delay: float) -> None:
    if stop.wait(first_delay):
        return
    while True:
        try:
            conn = db.connect(config.DB_PATH)
            try:
                db.init_schema(conn)
                run(conn)
            finally:
                conn.close()
        except Exception:
            log.exception("moneta: loop iteration failed")
        if stop.wait(interval_s):
            return


def start_background(run=run_once, first_delay: float = 20.0, interval_s: float | None = None):
    """Start the polling thread; returns it, or None (no token / lock held elsewhere)."""
    if not moneta_client.enabled():
        return None
    if not _acquire_lock():
        return None
    stop = threading.Event()
    t = threading.Thread(target=_loop, name="moneta-poll", daemon=True,
                         args=(stop, interval_s if interval_s is not None else config.MONETA_POLL_MIN * 60,
                               run, first_delay))
    t.stop_event = stop
    t.start()
    return t


# --------------------------------------------------------------------- UI

def status_view(conn) -> dict | None:
    """None when the feature is off; else what /doklady shows."""
    if not moneta_client.enabled():
        return None
    stav = get_stav(conn)
    cas = ""
    try:
        cas = datetime.fromisoformat(stav["last_run"]).astimezone().strftime("%H:%M")
    except (KeyError, ValueError):
        pass
    pocet = conn.execute("SELECT COUNT(*) FROM moneta_platby WHERE stav='nesparovano'").fetchone()[0]
    return {"cas": cas, "auth_failed": stav.get("auth_failed") == "1", "pocet": pocet}
