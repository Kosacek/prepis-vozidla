"""Best-effort push of a finished žádost to the Úkony Tracker.

This must NEVER raise into the žádost flow: on any failure the payload is
appended to ``DATA_DIR/failed_pushes.jsonl`` so it can be replayed later. The
tracker decides (by IČO match) whether to auto-create an úkon or queue it in its
Příchozí inbox — this side just fires the data.
"""
import json
import logging
import os
import uuid
from datetime import date

import requests

_log = logging.getLogger("prepis.tracker_push")

# Internal docker-network address of the tracker; overridable via env. The
# public https://evidence.spznaklic.cz works too (same key) if they're not on
# one docker network.
UKONY_API_URL = os.environ.get("UKONY_API_URL", "http://ukony-app:8090")
UKONY_API_KEY = os.environ.get("UKONY_API_KEY", "")
TIMEOUT = 2  # seconds — kept short; this is added to the generate latency


def build_payload(data: dict) -> dict:
    """Map the žádost form data to the tracker intake payload.

    `datum` is the REAL current date (the container runs TZ=Europe/Prague), i.e.
    the day the work is done — never the žádost's on-form date, which is
    deliberately post-dated to tomorrow for the úřad. We send only what an úkon
    needs (vehicle ids, mode, party names + IČO); no rodné číslo, no addresses.
    """
    return {
        "zadost_id": uuid.uuid4().hex,
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
    }


def _record_failure(data_dir: str, payload: dict, reason) -> None:
    try:
        path = os.path.join(data_dir, "failed_pushes.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"reason": str(reason), "payload": payload}, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover - last-resort logging
        _log.warning("could not record failed tracker push: %s", e)


def push(data: dict, data_dir: str) -> dict | None:
    """Fire-and-forget POST to the tracker. Returns the tracker's JSON on
    success, else None. Never raises."""
    payload = build_payload(data)
    headers = {"X-Api-Key": UKONY_API_KEY} if UKONY_API_KEY else {}
    try:
        r = requests.post(
            f"{UKONY_API_URL}/api/prichozi", json=payload, headers=headers, timeout=TIMEOUT
        )
        if r.status_code in (200, 201):
            return r.json()
        _record_failure(data_dir, payload, f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        _record_failure(data_dir, payload, e)
    return None
