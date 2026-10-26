"""Issue a doklad (PPD) from evidence through žádosti.

Žádosti own the numbering (one Excel ledger, never reused numbers) and the
PDF, so evidence only asks: POST /api/ppd/vystavit (spec 2026-10-26). The
returned doklad is stored at once and linked to exactly the chosen úkony.
Payment is NOT set here — the úkony get the orange "Zaplatit" instead.
"""
from __future__ import annotations

import re

import requests

import config
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import ppd_links

UCEL = "ZASTUPOVÁNÍ NA MMB"
MAX_UKONY = 30
MAX_CASTKA = 10_000_000


class IssueError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def validate(conn, payload) -> dict:
    """Checked request: firm, its úkony, payer, amount. Raises IssueError(400)."""
    if not isinstance(payload, dict):
        raise IssueError("Pošli údaje dokladu.")
    firma_id = payload.get("firma_id")
    firma = firmy_repo.get(conn, firma_id) if type(firma_id) is int else None
    if not firma or not firma["aktivni"]:
        raise IssueError("Vyber aktivní firmu.")
    ids = payload.get("ukony")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_UKONY
            or any(type(i) is not int for i in ids)):
        raise IssueError(f"Zaškrtni 1 až {MAX_UKONY} úkonů.")
    ukony = ukony_repo.list_by_ids(conn, ids)
    if len(ukony) != len(set(ids)) or any(u["firma_id"] != firma_id for u in ukony.values()):
        raise IssueError("Úkony musí patřit vybrané firmě.")
    castka = payload.get("castka")
    if type(castka) is not int or not 1 <= castka <= MAX_CASTKA:
        raise IssueError("Částka musí být celé číslo v korunách.")
    prijato_od = " ".join(str(payload.get("prijato_od") or "").split())
    if not prijato_od or len(prijato_od) > 120:
        raise IssueError("Vyplň Přijato od.")
    ico = re.sub(r"\s", "", str(payload.get("prijato_ico") or ""))
    if ico and not re.fullmatch(r"\d{1,12}", ico):
        raise IssueError("IČO smí mít jen číslice.")
    ucel = " ".join(str(payload.get("ucel") or UCEL).split())[:80] or UCEL
    ordered = sorted(ukony.values(), key=lambda u: (u["datum"], u["id"]))
    return {"firma": firma, "ukony": ordered, "castka": castka, "prijato_od": prijato_od,
            "prijato_ico": ico, "ucel": ucel,
            "zpracoval": payload.get("zpracoval") if isinstance(payload.get("zpracoval"), str) else None}


def vystavit(conn, req: dict) -> dict:
    """Ask žádosti for the doklad, store it, link it. Raises IssueError(502)."""
    if not config.ZADOSTI_API_URL:
        raise IssueError("Vystavení dokladů zatím není zapnuté.", 502)
    body = {"prijato_od": req["prijato_od"], "prijato_ico": req["prijato_ico"],
            "castka": req["castka"], "ucel": req["ucel"],
            "vozidla": [u["rz"] or u["vin"] for u in req["ukony"] if u["rz"] or u["vin"]],
            "zpracoval": req["zpracoval"]}
    try:
        response = requests.post(config.ZADOSTI_API_URL.rstrip("/") + "/api/ppd/vystavit", json=body,
                                 headers={"X-Api-Key": config.INTEGRATION_API_KEY}, timeout=20)
    except requests.RequestException as exc:
        raise IssueError("Žádosti neodpovídají, doklad se nevystavil. Zkus to za chvíli.", 502) from exc
    if response.status_code == 404:
        raise IssueError("Vystavení dokladů zatím není zapnuté.", 502)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 400 and isinstance(data, dict) and data.get("error"):
        raise IssueError(str(data["error"]), 502)
    doklad = data.get("doklad") if isinstance(data, dict) else None
    if response.status_code != 201 or not isinstance(doklad, dict):
        raise IssueError("Doklad se nepodařilo vystavit.", 502)
    row, _ = ppd_repo.upsert(conn, doklad)
    ppd_links.set_explicit(conn, row["cislo"], [u["id"] for u in req["ukony"]])
    print_url = str(data.get("print_url") or f"/ppd-print/{row['cislo']}")
    return {"cislo": row["cislo"], "print_url": config.ZADOSTI_PUBLIC_URL.rstrip("/") + print_url}
