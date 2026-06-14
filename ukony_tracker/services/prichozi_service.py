"""Intake of incoming žádosti from the zadosti app.

Flow (see spec R5): claim the zadost_id row first (UNIQUE backstops idempotency),
match the firm, then either auto-create the úkon (mode maps to a type AND exactly
one active firm matched) or leave the row pending for the Příchozí inbox.
"""
import sqlite3
from datetime import date

from repositories import prichozi_repo, typy_repo
from services import ingest_service, matching_service

# žádost mode → tracker úkon type for the AUTO-create path only. Modes not listed
# (notably 'zmena') never auto-create — they always wait in the inbox.
MODE_TO_TYP = {"prevod": "PŘEVOD", "zapis": "NOVÉ"}


def build_orv(serie: str | None, cislo: str | None) -> str | None:
    """ORV only when both halves are present (spec R6)."""
    s = (serie or "").strip()
    c = (cislo or "").strip()
    return f"{s}{c}".upper() if (s and c) else None


def _default_price(conn: sqlite3.Connection, typ_kod: str) -> float:
    t = typy_repo.get_by_kod(conn, typ_kod)
    if t and t["vychozi_cena"] is not None:
        return float(t["vychozi_cena"])
    return 0.0  # missing/NULL price degrades to 0, editable on the úkon (spec R2)


def _context_note(payload: dict) -> str | None:
    novy = (payload.get("novy_jmeno") or "").strip()
    puvodni = (payload.get("puvodni_jmeno") or "").strip()
    if novy and puvodni:
        return f"{novy} ← {puvodni}"
    return novy or puvodni or None


def _candidate_icos(payload: dict) -> list[str | None]:
    return [
        payload.get("puvodni_ico"),
        payload.get("novy_ico"),
        payload.get("puvodni_prov_ico"),
        payload.get("novy_prov_ico"),
    ]


def intake(conn: sqlite3.Connection, payload: dict) -> dict:
    """Process one incoming žádost.

    Returns ``{"status": "duplicate"|"auto"|"pending", "prichozi_id": int,
    "ukon_id"?: int}``.
    """
    zadost_id = payload.get("zadost_id")

    # Fast idempotency: an already-seen žádost is a no-op.
    if zadost_id:
        seen = prichozi_repo.get_by_zadost_id(conn, zadost_id)
        if seen:
            return {"status": "duplicate", "prichozi_id": seen["id"]}

    mode = (payload.get("mode") or "").strip().lower()
    rz = payload.get("rz")
    vin = payload.get("vin")
    orv = payload.get("orv") or build_orv(
        payload.get("osvedceni_serie"), payload.get("osvedceni_cislo")
    )
    datum = payload.get("datum") or date.today().isoformat()

    m = matching_service.match(conn, _candidate_icos(payload))
    # Suggest the matched firm; if ambiguous, suggest the first match as a hint.
    suggested = m["firma_id"] or (m["matched"][0]["id"] if m["matched"] else None)

    # Claim the row (UNIQUE on zadost_id wins the race against a concurrent retry).
    try:
        pid = prichozi_repo.create(
            conn,
            zadost_id=zadost_id,
            datum=datum,
            mode=mode,
            rz=rz, vin=vin, orv=orv,
            puvodni_jmeno=payload.get("puvodni_jmeno"),
            puvodni_ico=payload.get("puvodni_ico"),
            novy_jmeno=payload.get("novy_jmeno"),
            novy_ico=payload.get("novy_ico"),
            suggested_firma_id=suggested,
            status="pending",
            raw=payload,
        )
    except sqlite3.IntegrityError:
        seen = prichozi_repo.get_by_zadost_id(conn, zadost_id)
        return {"status": "duplicate", "prichozi_id": seen["id"] if seen else None}

    typ = MODE_TO_TYP.get(mode)
    if typ and m["firma_id"]:
        try:
            uid = ingest_service.pridat_ukon(
                conn,
                firma_id=m["firma_id"],
                datum=datum,
                typ_kod=typ,
                celkem=_default_price(conn, typ),
                rz=rz, vin=vin, orv=orv,
                poznamka=_context_note(payload),
                zdroj="zadosti",
            )
        except ingest_service.IngestError:
            return {"status": "pending", "prichozi_id": pid}  # surfaces in inbox
        prichozi_repo.update(conn, pid, status="auto", created_ukon_id=uid)
        return {"status": "auto", "ukon_id": uid, "prichozi_id": pid}

    return {"status": "pending", "prichozi_id": pid}
