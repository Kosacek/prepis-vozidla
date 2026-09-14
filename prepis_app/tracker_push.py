"""Best-effort push of a finished žádost to the Úkony Tracker.

This must NEVER raise into the žádost flow AND must NEVER block it either —
``push_async`` fires the POST from a background thread so the person waiting
for their PDF doesn't pay for a slow/unreachable tracker (measured 2.1s of a
4-5s /api/generate on the NAS's ARM box, almost all of it this call blocking).

Reliability does not get traded away for speed: the tracker dedups on
``zadost_id`` (UNIQUE constraint — see prichozi_service.intake), so replaying
a payload that already landed is always safe, never double-counts. On any
failure the payload is appended to ``DATA_DIR/failed_pushes.jsonl``, and
``retry_failed`` (called by app.py on a periodic background sweep, and once at
startup) resends every backlogged entry and drops only the ones that succeed.
The tracker decides (by IČO match) whether to auto-create an úkon or queue it
in its Příchozí inbox — this side just fires the data.
"""
import json
import logging
import os
import threading
import time
import uuid
from datetime import date

import requests

_log = logging.getLogger("prepis.tracker_push")

# fcntl is POSIX-only. Production is the Linux container (where the flock is
# the real concurrency guard for gunicorn's 2 workers + the sweep thread in
# each); on Windows dev we degrade to a no-op lock — single developer, no
# concurrency there. Same idiom as ppd.py.
try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows dev only
    _HAVE_FCNTL = False

# Internal docker-network address of the tracker; overridable via env. The
# public https://evidence.spznaklic.cz works too (same key) if they're not on
# one docker network.
UKONY_API_URL = os.environ.get("UKONY_API_URL", "http://ukony-app:8090")
UKONY_API_KEY = os.environ.get("UKONY_API_KEY", "")
# No longer added to /api/generate's latency (push runs off-thread), so this
# can afford to be generous: a slow-but-alive tracker now succeeds instead of
# being recorded as a false failure. 35 of the 35 pre-existing backlog entries
# were exactly this — "Read timed out" at the old TIMEOUT=2, not a real drop.
TIMEOUT = 8  # seconds, per attempt
RETRY_DELAYS = (1, 4)  # seconds between attempts, within one push_async call


def build_payload(data: dict) -> dict:
    """Map the žádost form data to the tracker intake payload.

    `datum` is the REAL current date (the container runs TZ=Europe/Prague), i.e.
    the day the work is done — never the žádost's on-form date, which is
    deliberately post-dated to tomorrow for the úřad. We send only what an úkon
    needs (vehicle ids, mode, party names + IČO); no rodné číslo, no addresses.
    """
    payload = {
        # Stable per-žádost id from the browser (regenerate → same id → the
        # tracker dedups on it, so no double úkon). Falls back to a fresh uuid.
        "zadost_id": (data.get("zadost_id") or uuid.uuid4().hex),
        "datum": date.today().isoformat(),
        "mode": data.get("mode", "prevod"),
        "rz": data.get("registracni_znacka"),
        "vin": data.get("vin"),
        "znacka": data.get("znacka"),  # brand+model (e.g. "Škoda Octavia") — helps ID the firm
        "osvedceni_serie": data.get("osvedceni_serie"),
        "osvedceni_cislo": data.get("osvedceni_cislo"),
        "puvodni_jmeno": data.get("puvodni_jmeno"),
        "puvodni_ico": data.get("puvodni_ico"),
        "novy_jmeno": data.get("novy_jmeno"),
        "novy_ico": data.get("novy_ico"),
        "puvodni_prov_ico": data.get("puvodni_prov_ico"),
        "novy_prov_ico": data.get("novy_prov_ico"),
        # Operator (provozovatel) NAMES — only when a distinct operator was
        # entered ("jiný provozovatel" checked). Lets the tracker inbox show the
        # real client instead of a leasing-company owner. IČOs above stay
        # unconditional so firm matching is unchanged.
        "puvodni_prov_jmeno": ((data.get("puvodni_prov_jmeno") or "").strip() or None)
            if data.get("puvodni_prov_jiny") else None,
        "novy_prov_jmeno": ((data.get("novy_prov_jmeno") or "").strip() or None)
            if data.get("novy_prov_jiny") else None,
        # Who filled this out (David/Roman/Petr), chosen in the app — the tracker
        # stores it as the úkon's `zpracoval` so we know who added each car.
        "profil": (data.get("profil") or "").strip() or None,
    }
    # Explicit assignment chosen on the last page (Evidence úkonu card): the
    # tracker then creates the úkon exactly as picked — right firm, type and
    # price — with no inbox sorting. Absent → the tracker auto-matches by IČO.
    try:
        fid = int(data.get("evidence_firma_id") or 0)
    except (TypeError, ValueError):
        fid = 0
    if fid:
        payload["firma_id"] = fid
        payload["typ_kod"] = (data.get("evidence_typ") or "").strip() or None
        cena = data.get("evidence_cena")
        if cena not in (None, ""):
            payload["celkem"] = cena
    # Optional úkon note typed on the last page (overrides the derived one).
    poznamka = (data.get("evidence_poznamka") or "").strip()
    if poznamka:
        payload["poznamka"] = poznamka
    # "ÚKON UŽ ZAPLACEN" checkbox — always sent (not just when true), so the
    # tracker's default of unpaid is an explicit choice, not a gap in the payload.
    payload["zaplaceno"] = bool(data.get("evidence_zaplaceno"))
    return payload


def fetch_meta() -> dict | None:
    """GET the evidence firms/types/prices for the last-page picker. Returns the
    parsed JSON ({firmy, typy, ceny}), or None on any failure — the picker then
    simply isn't offered. Best-effort; never raises."""
    headers = {"X-Api-Key": UKONY_API_KEY} if UKONY_API_KEY else {}
    try:
        r = requests.get(
            f"{UKONY_API_URL}/api/evidence-meta", headers=headers, timeout=4
        )
        if r.status_code == 200:
            return r.json()
        _log.warning("evidence-meta HTTP %s", r.status_code)
    except Exception as e:
        _log.warning("evidence-meta fetch failed: %s", e)
    return None


def _failed_path(data_dir: str) -> str:
    return os.path.join(data_dir, "failed_pushes.jsonl")


def _with_lock(data_dir: str, fn):
    """Run `fn()` while holding an exclusive lock on the failed-pushes file —
    same guard ppd.py uses for its ledger, needed here because every gunicorn
    worker runs its own periodic sweep thread against the same file."""
    os.makedirs(data_dir, exist_ok=True)
    lock_fd = open(_failed_path(data_dir) + ".lock", "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)  # blocking
        return fn()
    finally:
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()


def _record_failure(data_dir: str, payload: dict, reason) -> None:
    def _append():
        try:
            with open(_failed_path(data_dir), "a", encoding="utf-8") as f:
                f.write(json.dumps({"reason": str(reason), "payload": payload},
                                    ensure_ascii=False) + "\n")
        except Exception as e:  # pragma: no cover - last-resort logging
            _log.warning("could not record failed tracker push: %s", e)
    _with_lock(data_dir, _append)


def _post_once(payload: dict) -> dict | str:
    """One attempt. Returns the tracker's parsed JSON on success, else a
    short string describing why it failed (never raises)."""
    headers = {"X-Api-Key": UKONY_API_KEY} if UKONY_API_KEY else {}
    try:
        r = requests.post(f"{UKONY_API_URL}/api/prichozi", json=payload,
                          headers=headers, timeout=TIMEOUT)
        if r.status_code in (200, 201):
            return r.json()
        return f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return str(e)


def push(data: dict, data_dir: str) -> dict | None:
    """Build the payload and try to deliver it now, retrying transient
    failures a couple of times before giving up. Returns the tracker's JSON
    on success, else None. Never raises. Runs SYNCHRONOUSLY — call this from
    a background thread (``push_async``) unless the caller genuinely needs to
    block on the result (tests do)."""
    payload = build_payload(data)
    last_reason = "no attempt made"
    for attempt, delay in enumerate((0,) + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        result = _post_once(payload)
        if not isinstance(result, str):
            return result
        last_reason = result
    _record_failure(data_dir, payload, last_reason)
    return None


def push_async(data: dict, data_dir: str) -> None:
    """Fire-and-forget: hands the žádost off to a background thread so
    /api/generate doesn't wait on the tracker at all. Whoever's waiting for
    their PDF already has it by the time this even starts its first attempt."""
    threading.Thread(target=push, args=(data, data_dir), daemon=True).start()


def retry_failed(data_dir: str) -> int:
    """Resend every backlogged payload; drop only the ones that succeed (or
    that the tracker reports as an already-landed duplicate — same outcome,
    the úkon exists either way). Returns how many are still outstanding.

    Safe to call anytime, from any worker, on any schedule: the tracker's
    UNIQUE constraint on zadost_id makes resending an already-delivered
    payload a no-op, never a duplicate úkon.
    """
    def _run():
        path = _failed_path(data_dir)
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        still_failing = []
        for line in lines:
            try:
                entry = json.loads(line)
                payload = entry["payload"]
            except Exception:
                continue  # a corrupt line is not worth blocking the sweep over
            result = _post_once(payload)
            if isinstance(result, str):
                entry["reason"] = result
                still_failing.append(json.dumps(entry, ensure_ascii=False))
        if still_failing:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(still_failing) + "\n")
            os.replace(tmp, path)
        elif os.path.exists(path):
            os.remove(path)
        return len(still_failing)
    return _with_lock(data_dir, _run)


_sweep_started = False
_sweep_lock = threading.Lock()


def start_sweep(data_dir: str, interval_s: int = 300) -> None:
    """Start the periodic retry sweep, once per process. Call from app.py at
    import time; a no-op on every call after the first in the same process."""
    global _sweep_started
    with _sweep_lock:
        if _sweep_started:
            return
        _sweep_started = True

    def _loop():
        while True:
            try:
                n = retry_failed(data_dir)
                if n:
                    _log.warning("tracker sweep: %d push(es) still failing", n)
            except Exception as e:  # pragma: no cover - the sweep must never die
                _log.warning("tracker sweep error: %s", e)
            time.sleep(interval_s)

    threading.Thread(target=_loop, daemon=True).start()
