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
STRANY = ("provozovatel", "vlastnik")


class IssueError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _strana(jmeno, ico) -> dict | None:
    jmeno = " ".join(str(jmeno or "").split())[:120]
    return {"jmeno": jmeno, "ico": re.sub(r"\D", "", str(ico or ""))[:12]} if jmeno else None


def zadosti(conn, ukon_ids) -> dict[int, dict]:
    """The žádost each úkon came from, with its payer candidates.

    {ukon_id: {"id": zadost_id, "provozovatel": {jmeno, ico} | None,
    "vlastnik": {...} | None}}. Žádosti send the operator's name only when one
    was entered separately; without it the owner is the operator, and a stray
    operator IČO alone is not a party. Manual úkony are simply absent.
    """
    ids = sorted({i for i in ukon_ids if type(i) is int})
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT created_ukon_id, zadost_id, novy_jmeno, novy_ico, novy_prov_jmeno, novy_prov_ico"
        f" FROM prichozi WHERE zadost_id IS NOT NULL AND created_ukon_id IN ({','.join('?' * len(ids))})"
        " ORDER BY id", ids).fetchall()
    return {r["created_ukon_id"]: {
        "id": r["zadost_id"],
        "provozovatel": _strana(r["novy_prov_jmeno"], r["novy_prov_ico"]),
        "vlastnik": _strana(r["novy_jmeno"], r["novy_ico"]),
    } for r in rows}


def _platce(conn, payload, ukon_ids) -> dict:
    """Optional payer from a žádost: {zadost_id, strana} for žádosti to look up
    the address, or {} when the doklad is on the firm / a typed name."""
    zadost_id, strana = payload.get("zadost_id"), payload.get("strana")
    if zadost_id is None and strana is None:
        return {}
    known = {z["id"] for z in zadosti(conn, ukon_ids).values()}
    if strana not in STRANY or not isinstance(zadost_id, str) or zadost_id not in known:
        raise IssueError("Plátce nepatří k vybraným úkonům — vyber ho znovu.")
    return {"zadost_id": zadost_id, "strana": strana}


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
    # One id per doklad, reused on retry: žádosti return the doklad already
    # issued for it instead of a second number (timeout retry, double click).
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", request_id):
        raise IssueError("Chybí request_id dokladu — obnov stránku a zkus to znovu.")
    platce = _platce(conn, payload, ids)
    ordered = sorted(ukony.values(), key=lambda u: (u["datum"], u["id"]))
    return {"firma": firma, "ukony": ordered, "castka": castka, "prijato_od": prijato_od,
            "prijato_ico": ico, "ucel": ucel, "request_id": request_id, "platce": platce,
            "zpracoval": payload.get("zpracoval") if isinstance(payload.get("zpracoval"), str) else None}


def vystavit(conn, req: dict) -> dict:
    """Ask žádosti for the doklad, store it, link it. Raises IssueError(502)."""
    if not config.ZADOSTI_API_URL:
        raise IssueError("Vystavení dokladů zatím není zapnuté.", 502)
    body = {"prijato_od": req["prijato_od"], "prijato_ico": req["prijato_ico"],
            "castka": req["castka"], "ucel": req["ucel"],
            "vozidla": [u["rz"] or u["vin"] for u in req["ukony"] if u["rz"] or u["vin"]],
            "zpracoval": req["zpracoval"], "request_id": req["request_id"],
            # Payer picked from a žádost: žádosti fill in that party's address.
            **req.get("platce", {})}
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
    # 201 = new doklad, 200 = the one already issued for this request_id.
    if response.status_code not in (200, 201) or not isinstance(doklad, dict):
        raise IssueError("Doklad se nepodařilo vystavit.", 502)
    row, _ = ppd_repo.upsert(conn, doklad)
    ppd_links.set_explicit(conn, row["cislo"], [u["id"] for u in req["ukony"]])
    print_url = str(data.get("print_url") or f"/ppd-print/{row['cislo']}")
    return {"cislo": row["cislo"], "print_url": config.ZADOSTI_PUBLIC_URL.rstrip("/") + print_url}
