"""ORV → VIN lookup against the dataovozidlech.cz registry.

Same source and shape as the zadosti app's ``lookup_orv``: the úkon form sends
the combined ORV (série + číslo, e.g. "UBE037263") and gets back the VIN so the
operator doesn't have to retype it. Best-effort — never raises; on any problem it
returns ``{"success": False, "error": <message>}`` for the UI to show.
"""
from __future__ import annotations

import requests

import config

_API_URL = "https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2"
_MIN_ORV_LEN = 9  # 3-letter série + 6-digit číslo
_TIMEOUT = 8


def lookup_vin(orv: str) -> dict:
    """Look up a vehicle by its ORV and return its VIN.

    Returns ``{"success": True, "vin": str, "znacka": str}`` on a hit, else
    ``{"success": False, "error": str}``.
    """
    api_key = config.DATAOVOZIDLECH_API_KEY
    if not api_key:
        return {"success": False, "error": "Chybí DATAOVOZIDLECH_API_KEY"}

    orv_norm = (orv or "").replace(" ", "").upper()
    if len(orv_norm) < _MIN_ORV_LEN:
        return {"success": False, "error": "Neúplné ORV"}

    try:
        r = requests.get(
            _API_URL,
            params={"orv": orv_norm},
            headers={"api_key": api_key},
            timeout=_TIMEOUT,
        )
        resp = r.json()
    except Exception:
        return {"success": False, "error": "Chyba spojení"}

    if r.status_code == 200 and resp.get("Status") == 1 and resp.get("Data"):
        d = resp["Data"]
        znacka = " ".join(filter(None, [
            d.get("TovarniZnacka", ""), d.get("ObchodniOznaceni", ""),
        ])).strip()
        return {"success": True, "vin": d.get("VIN", "") or "", "znacka": znacka}
    if resp.get("Status") == 3:
        return {"success": False, "error": "Vozidlo nenalezeno"}
    return {"success": False, "error": f"Chyba registru (status {resp.get('Status')})"}
