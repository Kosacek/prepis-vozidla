"""Delete a doklad (PPD) from evidence through žádosti.

Žádosti own the ledger: POST /api/ppd/<cislo>/smazat takes the doklad out of
the live ledger (their backup keeps a copy, so žádosti can restore it).
Evidence then only marks its own copy smazano=1. Úkony are never touched — on
27. 10. 2026 the trash on Doklady deleted úkon 1533 instead of doklad 183.
"""
from __future__ import annotations

import logging

import requests

import config
from repositories import ppd_repo
from services import ppd_links

log = logging.getLogger(__name__)


def _kratke(cislo: int) -> str:
    """Faktura 20260001 is "0001" in the apps."""
    return f"{cislo % 10000:04d}" if cislo > 99999 else str(cislo)


class DeleteError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def smazat(conn, cislo: int, kdo: str | None = None) -> None:
    """Ask žádosti to storno doklad `cislo`, then grey it here. Raises DeleteError.

    Only an explicit {"removed": true} marks it here: {"removed": false} means
    žádosti did NOT storno it (13. 11. 2026: faktura 0001 got hidden while
    žádosti kept it live), so evidence keeps it live and says so."""
    if not config.ZADOSTI_API_URL:
        raise DeleteError("Mazání dokladů zatím není zapnuté.", 503)
    doklad = ppd_repo.get_by_cislo(conn, cislo)
    if doklad is None:
        raise DeleteError(f"Doklad č. {cislo} tu není.", 404)
    if doklad["smazano"]:
        raise DeleteError(f"Doklad č. {cislo} už je smazaný.", 409)
    try:
        # No redirects: without the endpoint the login gate answers 302 → a 200 login page.
        extra = {"json": {"kdo": kdo}} if kdo else {}
        response = requests.post(f"{config.ZADOSTI_API_URL.rstrip('/')}/api/ppd/{cislo}/smazat",
                                 headers={"X-Api-Key": config.INTEGRATION_API_KEY},
                                 timeout=20, allow_redirects=False, **extra)
    except requests.RequestException as exc:
        log.warning("Doklad %s: žádosti unreachable: %s", cislo, exc)
        raise DeleteError("Žádosti neodpovídají, doklad se nesmazal. Zkus to za chvíli.") from exc
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code != 200 or not isinstance(data, dict) or type(data.get("removed")) is not bool:
        log.warning("Doklad %s: žádosti refused the delete (HTTP %s)", cislo, response.status_code)
        raise DeleteError(f"Doklad č. {_kratke(cislo)} se nepodařilo smazat.")
    if data["removed"] is not True:
        log.warning("Doklad %s: žádosti answered removed=false, kept live here", cislo)
        raise DeleteError(f"Žádosti doklad č. {_kratke(cislo)} nestornovaly – zkontroluj ho v žádostech.", 409)
    ppd_repo.mark_deleted(conn, cislo, kdo)
    ppd_links.invalidate()
