"""Tisk / Sdílet kódem for a doklad on /doklady (2.8).

Doklady live in žádosti (ledger + PDF), so evidence only links or asks:
- Tisk = žádosti's A5 print page, ZADOSTI_PUBLIC_URL/ppd-print/<cislo>;
- Sdílet kódem = žádosti POST /api/ppd/<cislo>/sdilet with the integration
  key → {"sdilet": "/4821", "plati_dni": 30}; the public link is
  ZADOSTI_PUBLIC_URL + sdilet (opens without a login, expires in 30 days).
A žádosti build without that endpoint answers a non-JSON 404 (or the login
redirect): evidence then says the feature isn't there yet, so it starts
working the moment žádosti ship it — no evidence redeploy needed.
"""
from __future__ import annotations

import logging
import re

import requests

import config
from repositories import ppd_repo

log = logging.getLogger(__name__)

_KOD = re.compile(r"/[A-Za-z0-9_-]{2,64}")
_TTL_DEFAULT = 30
NEUMI = "Sdílení kódem žádosti zatím neumí."


class ShareError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def tisk_base() -> str:
    """Prefix of the print link; the page appends the doklad number."""
    return config.ZADOSTI_PUBLIC_URL.rstrip("/") + "/ppd-print/"


def sdilet(conn, cislo: int) -> dict:
    """Share code for doklad `cislo` from žádosti. Raises ShareError."""
    if not config.ZADOSTI_API_URL:
        raise ShareError("Sdílení dokladů zatím není zapnuté.", 503)
    doklad = ppd_repo.get_by_cislo(conn, cislo)
    if doklad is None:
        raise ShareError(f"Doklad č. {cislo} tu není.", 404)
    if doklad["smazano"]:
        raise ShareError(f"Doklad č. {cislo} je smazaný.", 409)
    try:
        # No redirects: without the endpoint the login gate answers 302 → a 200 login page.
        response = requests.post(f"{config.ZADOSTI_API_URL.rstrip('/')}/api/ppd/{cislo}/sdilet",
                                 headers={"X-Api-Key": config.INTEGRATION_API_KEY},
                                 timeout=15, allow_redirects=False)
    except requests.RequestException as exc:
        log.warning("Doklad %s: žádosti unreachable for a share code: %s", cislo, exc)
        raise ShareError("Žádosti neodpovídají, kód se nevytvořil. Zkus to za chvíli.") from exc
    try:
        data = response.json()
    except ValueError:
        data = None
    error = data.get("error") if isinstance(data, dict) else None
    if response.status_code in (301, 302, 303, 307, 308, 404, 405) and not error:
        raise ShareError(NEUMI, 501)
    if response.status_code == 404:
        raise ShareError(str(error)[:200], 404)
    kod = data.get("sdilet") if isinstance(data, dict) else None
    if response.status_code != 200 or not isinstance(kod, str) or not _KOD.fullmatch(kod):
        log.warning("Doklad %s: žádosti gave no share code (HTTP %s)", cislo, response.status_code)
        raise ShareError("Kód se nepodařilo vytvořit.")
    dni = data.get("plati_dni")
    dni = dni if type(dni) is int and 0 < dni <= 365 else _TTL_DEFAULT
    return {"kod": kod[1:], "url": config.ZADOSTI_PUBLIC_URL.rstrip("/") + kod, "plati_dni": dni}
