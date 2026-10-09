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

import requests

from tracker_push import UKONY_API_URL, UKONY_API_KEY, TIMEOUT, RETRY_DELAYS

_log = logging.getLogger("prepis.ppd_push")

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

    return {
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


def _failed_path(data_dir: str) -> str:
    return os.path.join(data_dir, "failed_ppd_pushes.jsonl")


def _with_lock(data_dir: str, fn):
    """Serialize appends and sweeps across gunicorn workers with our own lock."""
    os.makedirs(data_dir, exist_ok=True)
    lock_fd = open(_failed_path(data_dir) + ".lock", "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        return fn()
    finally:
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()


def _record_failure(data_dir: str, record: dict, reason) -> None:
    def _append():
        with open(_failed_path(data_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps({"reason": str(reason), "record": record},
                               ensure_ascii=False) + "\n")
    try:
        _with_lock(data_dir, _append)
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


def push(record: dict, data_dir: str) -> dict | None:
    """Deliver synchronously with the tracker's retry delays; queue failures."""
    last_reason = "no attempt made"
    for delay in (0,) + RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        result = _put_once(record)
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
    def _run():
        path = _failed_path(data_dir)
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
        still_failing = []
        for line in lines:
            try:
                entry = json.loads(line)
                record = entry["record"]
            except Exception:
                # Retain unreadable entries for inspection; never lose a receipt.
                still_failing.append(line)
                continue
            result = _put_once(record)
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
