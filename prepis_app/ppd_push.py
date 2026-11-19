"""Best-effort, asynchronous PPD upserts to evidence.

The local ledger owns numbering; evidence receives a copy of every receipt.
Failures (including an endpoint not yet deployed) stay in a separate JSONL
queue until the existing tracker sweep can deliver them.
"""
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from uuid import uuid4

import requests

import ppd
import storno
from tracker_push import UKONY_API_URL, UKONY_API_KEY, TIMEOUT, RETRY_DELAYS

_log = logging.getLogger("prepis.ppd_push")
_DORUCENI_ZAMKY = tuple(threading.Lock() for _ in range(32))
_FRONTA_ZAMEK = threading.Lock()

# Same POSIX flock / Windows dev fallback as tracker_push.py and ppd.py.
try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows dev only
    _HAVE_FCNTL = False


def build_record(row: dict, *, zadost_id: str = "", smazano: bool = False) -> dict:
    """Map an issue record, backup row or ledger row to the evidence contract."""
    amount = row.get("castka", row.get("amount"))
    try:
        amount = max(0, int(round(float("".join(str(amount or 0).split()).replace(",", ".")))))
    except (TypeError, ValueError, OverflowError):
        amount = 0

    def text(value):
        return str(value if value is not None else "").strip()

    record = {
        "cislo": int(row.get("cislo", row.get("number"))),
        "datum": text(row.get("datum", row.get("date"))),
        "prijato_od": text(row.get("prijato_od", row.get("payer"))),
        "prijato_ico": text(row.get("ico", row.get("payer_ico", row.get("prijato_ico")))),
        "castka": amount,
        "ucel": text(row.get("ucel", row.get("purpose"))),
        "vozidlo": (text(row.get("spz")) or text(row.get("vin"))
                    or text(row.get("vehicle")) or text(row.get("vozidlo"))),
        "zadost_id": zadost_id or "",
        "smazano": bool(smazano),
    }
    # Faktura (1.33.0): jen faktura nese druh + splatnost — PPD tělo zůstává
    # beze změny a evidence (ppd_repo) tak starému druhu nic nepřepíše.
    if row.get("druh") == "faktura":
        record["druh"] = "faktura"
        record["splatnost"] = text(row.get("splatnost"))
    return record


def _failed_path(data_dir: str) -> str:
    return os.path.join(data_dir, "failed_ppd_pushes.jsonl")


def _with_lock(data_dir: str, fn):
    """Serialize appends and sweeps across gunicorn workers with our own lock."""
    os.makedirs(data_dir, exist_ok=True)
    with _FRONTA_ZAMEK, open(_failed_path(data_dir) + ".lock", "a+") as lock_fd:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def enqueue(record: dict, data_dir: str, *, reason: str = "čeká na odeslání") -> None:
    """Ulož push dřív, než se předá vláknu."""
    entry = {"id": uuid4().hex, "reason": reason, "record": record}
    radek = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")

    def _append():
        with open(_failed_path(data_dir), "a+b") as f:
            if f.tell():
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.write(b"\n")
            f.write(radek)
            f.flush()
            os.fsync(f.fileno())

    _with_lock(data_dir, _append)


def _record_failure(data_dir: str, record: dict, reason) -> None:
    try:
        enqueue(record, data_dir, reason=str(reason))
    except Exception as e:  # pragma: no cover - last-resort logging
        _log.warning("could not record failed PPD push: %s", e)


def _put_once(record: dict) -> dict | str:
    """One attempt: parsed JSON on success, a reason on failure; never raises."""
    headers = {"X-Api-Key": UKONY_API_KEY} if UKONY_API_KEY else {}
    try:
        r = requests.put(f"{UKONY_API_URL}/api/ppd/{record['cislo']}", json=record,
                         headers=headers, timeout=TIMEOUT)
        if 200 <= r.status_code < 300:
            return r.json()
        return f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return str(e)


def _put_aktualni(data_dir: str, record: dict) -> dict | str:
    """PUTy stejného čísla se nepředbíhají. Starší pokus po změně stavu zahodíme."""
    try:
        number = int(record["cislo"])
        druh = record.get("druh") or "ppd"
        index = number % len(_DORUCENI_ZAMKY)
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, f"doklad_push_{index}.lock")
        with _DORUCENI_ZAMKY[index], open(path, "a+b") as f:
            if _HAVE_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                with storno.transakce(data_dir):
                    stav = storno.stav(data_dir).get((druh, number), {})
                    smazano = ppd.je_stornovany(data_dir, number) if druh == "ppd" else bool(stav.get("storno"))
                    if smazano != bool(record.get("smazano")):
                        return {}
                    if stav.get("storno") and "storno_cas" in record:
                        record = {**record, "storno_cas": stav["storno_cas"], "storno_kdo": stav["storno_kdo"]}
                if "storno_cas" in record and not record.get("zadost_id"):
                    from ppd_api import zadost_id_dokladu
                    zadost_id = zadost_id_dokladu(data_dir, number, druh=druh)
                    if zadost_id:
                        record = {**record, "zadost_id": zadost_id}
                return _put_once(record)
            finally:
                if _HAVE_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        return str(e)


def push(record: dict, data_dir: str) -> dict | None:
    """Deliver synchronously with the tracker's retry delays; queue failures."""
    last_reason = "no attempt made"
    for delay in (0,) + RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        result = _put_aktualni(data_dir, record)
        if not isinstance(result, str):
            return result
        last_reason = result
    _record_failure(data_dir, record, last_reason)
    return None


def push_async(record: dict, data_dir: str) -> None:
    """Hand delivery to a background thread so the request never waits."""
    threading.Thread(target=push, args=(record, data_dir), daemon=True).start()


def retry_failed(data_dir: str) -> int:
    """Resend the backlog once, drop successes and return the remaining count."""
    path = _failed_path(data_dir)

    def read_queue():
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return b""

    def parse(line):
        try:
            entry = json.loads(line)
        except ValueError:
            return None, line
        if not isinstance(entry, dict) or "record" not in entry:
            return None, line
        entry_id = entry.get("id")
        return entry, entry_id if isinstance(entry_id, str) and entry_id else line

    snapshot = _with_lock(data_dir, read_queue)
    if not snapshot:
        return 0
    # Čekání na Evidenci nesmí držet zámek potřebný pro uložení nového storna.
    outcomes = defaultdict(deque)
    for line in snapshot.split(b"\n"):
        entry, key = parse(line)
        if entry is not None:
            outcomes[key].append(_put_aktualni(data_dir, entry["record"]))

    def save_queue():
        current = read_queue()
        remaining = []
        for line in current.split(b"\n"):
            if not line.strip():
                continue
            entry, key = parse(line)
            if entry is not None and outcomes.get(key):
                result = outcomes[key].popleft()
                if not isinstance(result, str):
                    continue
                entry["reason"] = result
                line = json.dumps(entry, ensure_ascii=False).encode("utf-8")
            remaining.append(line)
        if remaining:
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(b"\n".join(remaining) + b"\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        elif current:
            os.remove(path)
        return len(remaining)

    return _with_lock(data_dir, save_queue)
