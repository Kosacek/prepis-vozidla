"""„Přidat do evidence" ze skenu ORV.

Postup v kanceláři: auto se nejdřív zapíše (žádost o zápis má VIN, RZ ještě
neexistuje → úkon v evidenci má RZ prázdnou). Po registraci přijde ORV s
přidělenou RZ. Tady se z naskenovaného ORV:

1. najdou úkony toho auta v evidenci (podle VIN),
2. do úkonu, kde chybí, se doplní RZ a číslo ORV,
3. nebo se založí nový úkon (firma / typ / cena jako na poslední straně).

Hledání a doplnění volají endpointy, které evidence teprve dostane — spec je v
ukony_tracker/docs/superpowers/specs/2026-10-08-api-hledat-a-doplnit-z-orv.md.
Dokud neexistují (404), hledání vrátí `k_dispozici: False` a UI nabídne jen
nový úkon. Založení nového úkonu jde přes existující /api/prichozi — stejnou
cestou jako hotové žádosti (zpracoval, zaplaceno, ochrana proti duplicitě).

Klíč k evidenci zůstává na serveru; prohlížeč volá jen naše /api/evidence/*.
"""
from __future__ import annotations

import re
import uuid
from datetime import date

import requests

import tracker_push as _tp

TIMEOUT = 8

_RZ = re.compile(r"^[A-Z0-9]{5,8}$")
_VIN = re.compile(r"^[A-Z0-9]{5,17}$")
_ORV = re.compile(r"^[A-Z]{3}[0-9]{6}$")


class EvidenceError(Exception):
    """Chyba, kterou má smysl ukázat uživateli. `status` jde do HTTP odpovědi."""

    def __init__(self, zprava: str, status: int = 502, data: dict | None = None):
        super().__init__(zprava)
        self.zprava = zprava
        self.status = status
        self.data = data or {}


def norm(hodnota) -> str:
    """Velká písmena, bez mezer a pomlček — RZ, VIN i ORV se tak píšou různě."""
    return re.sub(r"[\s\-]", "", str(hodnota or "")).upper()


def _url(cesta: str) -> str:
    return f"{_tp.UKONY_API_URL}{cesta}"


def _hlavicky() -> dict:
    return {"X-Api-Key": _tp.UKONY_API_KEY} if _tp.UKONY_API_KEY else {}


def _je_json_chyba(r) -> bool:
    """404 z evidence může znamenat dvě věci: „úkon neexistuje" (vrací JSON
    s `error`, podle spec) nebo „endpoint ještě neexistuje" (holá 404 z Flasku)."""
    try:
        return "error" in (r.json() or {})
    except ValueError:
        return False


def hledat(vin, rz) -> dict:
    """Úkony daného auta napříč firmami: {k_dispozici, ukony}."""
    vin, rz = norm(vin), norm(rz)
    if vin and not _VIN.match(vin):
        raise EvidenceError("Neplatný VIN.", 400)
    if rz and not _RZ.match(rz):
        raise EvidenceError("Neplatná RZ.", 400)
    if not vin and not rz:
        raise EvidenceError("Ze skenu nevyšel VIN ani RZ — není podle čeho hledat.", 400)
    params = {k: v for k, v in (("vin", vin), ("rz", rz)) if v}
    try:
        r = requests.get(_url("/api/ukony/hledat"), params=params,
                         headers=_hlavicky(), timeout=TIMEOUT)
    except requests.RequestException:
        raise EvidenceError("Evidence neodpovídá.")
    if r.status_code == 404 and not _je_json_chyba(r):
        return {"k_dispozici": False, "ukony": []}
    if r.status_code != 200:
        raise EvidenceError(f"Evidence vrátila chybu (HTTP {r.status_code}).")
    return {"k_dispozici": True, "ukony": (r.json() or {}).get("ukony", [])}


def doplnit(uid, rz=None, orv=None) -> dict:
    """Doplní RZ / číslo ORV do úkonu — jen do prázdných polí (to hlídá evidence)."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        raise EvidenceError("Neplatné číslo úkonu.", 400)
    if uid <= 0:
        raise EvidenceError("Neplatné číslo úkonu.", 400)
    rz, orv = norm(rz), norm(orv)
    if rz and not _RZ.match(rz):
        raise EvidenceError("Neplatná RZ.", 400)
    if orv and not _ORV.match(orv):
        raise EvidenceError("Neplatné číslo ORV (3 písmena + 6 číslic).", 400)
    if not rz and not orv:
        raise EvidenceError("Není co doplnit — chybí RZ i číslo ORV.", 400)
    telo = {k: v for k, v in (("rz", rz), ("orv", orv)) if v}
    try:
        r = requests.post(_url(f"/api/ukony/{uid}/doplnit"), json=telo,
                          headers=_hlavicky(), timeout=TIMEOUT)
    except requests.RequestException:
        raise EvidenceError("Evidence neodpovídá.")
    if r.status_code == 200:
        return r.json()
    if r.status_code == 409:
        d = r.json() or {}
        raise EvidenceError(d.get("error") or "V úkonu už je jiná hodnota.", 409,
                            {"pole": d.get("pole"), "stavajici": d.get("stavajici")})
    if r.status_code == 404:
        if _je_json_chyba(r):
            raise EvidenceError("Úkon v evidenci už neexistuje.", 404)
        raise EvidenceError("Doplňování v evidenci zatím není k dispozici.", 501)
    if r.status_code == 400:
        raise EvidenceError((r.json() or {}).get("error") or "Evidence údaje odmítla.", 400)
    raise EvidenceError(f"Evidence vrátila chybu (HTTP {r.status_code}).")


def zalozit(*, vin=None, rz=None, orv=None, firma_id=None, typ_kod=None,
            celkem=None, poznamka=None, zaplaceno=False, profil=None,
            zadost_id=None) -> dict:
    """Nový úkon přes /api/prichozi s výslovnou firmou a typem (založí se rovnou).

    Vrací odpověď evidence: status `auto` (+ ukon_id), `pending` (čeká v
    Příchozí — typicky „možný duplikát", + duplicate_ukon_id) nebo `duplicate`
    (stejný požadavek už prošel — dvojklik)."""
    vin, rz, orv = norm(vin), norm(rz), norm(orv)
    if not vin and not rz:
        raise EvidenceError("Chybí VIN i RZ — úkon by nešel dohledat.", 400)
    if rz and not _RZ.match(rz):
        raise EvidenceError("Neplatná RZ.", 400)
    if vin and not _VIN.match(vin):
        raise EvidenceError("Neplatný VIN.", 400)
    if orv and not _ORV.match(orv):
        orv = ""   # číslo ORV je jen bonus — špatně přečtené nesmí zablokovat úkon
    try:
        firma_id = int(firma_id)
    except (TypeError, ValueError):
        raise EvidenceError("Vyber firmu.", 400)
    typ_kod = str(typ_kod or "").strip()
    if not typ_kod:
        raise EvidenceError("Vyber typ úkonu.", 400)
    if celkem in (None, ""):
        celkem = None      # evidence doplní cenu firmy
    else:
        try:
            celkem = float(celkem)
        except (TypeError, ValueError):
            raise EvidenceError("Neplatná cena.", 400)
        if celkem < 0:
            raise EvidenceError("Cena nemůže být záporná.", 400)
    payload = {
        "zadost_id": zadost_id or f"orv-{uuid.uuid4().hex}",
        "mode": "orv",
        "datum": date.today().isoformat(),
        "vin": vin or None, "rz": rz or None, "orv": orv or None,
        "firma_id": firma_id, "typ_kod": typ_kod, "celkem": celkem,
        "poznamka": (str(poznamka).strip() or None) if poznamka else None,
        "zaplaceno": bool(zaplaceno),
        "profil": (str(profil).strip() or None) if profil else None,
    }
    try:
        r = requests.post(_url("/api/prichozi"), json=payload,
                          headers=_hlavicky(), timeout=TIMEOUT)
    except requests.RequestException:
        raise EvidenceError("Evidence neodpovídá — úkon se nezapsal.")
    if r.status_code in (200, 201):
        return r.json()
    raise EvidenceError(f"Evidence úkon nepřijala (HTTP {r.status_code}).")
