"""What žádosti can issue right now: GET /api/ppd/moznosti -> {"faktura": bool}.

Evidence shows the "Hotově / Převodem" choice in Nový doklad only when žádosti
say faktura is available (FAKTURA_IBAN set there). The answer is cached for
about five minutes; any error means "no faktura", so the PPD-only flow stays
exactly as it was.
"""
from __future__ import annotations

import logging
import time

import requests

import config

log = logging.getLogger(__name__)

TTL_OK = 300.0     # seconds an answer is trusted
TTL_ERROR = 30.0   # a failure is retried sooner than a real answer
_cache: dict = {"until": 0.0, "value": None, "key": None}


def reset_cache() -> None:
    _cache.update(until=0.0, value=None, key=None)


def _fetch() -> dict:
    url = config.ZADOSTI_API_URL.rstrip("/") + "/api/ppd/moznosti"
    try:
        response = requests.get(url, headers={"X-Api-Key": config.INTEGRATION_API_KEY},
                                timeout=5, allow_redirects=False)
        data = response.json() if response.status_code == 200 else None
    except (requests.RequestException, ValueError) as exc:
        log.warning("žádosti /api/ppd/moznosti: %s", exc)
        return {"faktura": False, "ok": False}
    if not isinstance(data, dict) or type(data.get("faktura")) is not bool:
        return {"faktura": False, "ok": False}
    dni = data.get("splatnost_dni")
    return {"faktura": data["faktura"], "ok": True,
            "splatnost_dni": dni if type(dni) is int and 0 < dni <= 365 else None}


def moznosti() -> dict:
    """{"faktura": bool, ...}; never raises."""
    if not config.ZADOSTI_API_URL:
        return {"faktura": False, "ok": False}
    now = time.monotonic()
    key = (config.ZADOSTI_API_URL, config.INTEGRATION_API_KEY)
    if _cache["value"] is not None and _cache["key"] == key and now < _cache["until"]:
        return _cache["value"]
    value = _fetch()
    _cache.update(value=value, key=key, until=now + (TTL_OK if value["ok"] else TTL_ERROR))
    return value


def faktura_dostupna() -> bool:
    return bool(moznosti()["faktura"])
