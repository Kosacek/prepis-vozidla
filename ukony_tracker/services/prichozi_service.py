"""Intake of incoming žádosti from the zadosti app.

Flow (see spec R5): claim the zadost_id row first (UNIQUE backstops idempotency),
match the firm, then either auto-create the úkon (mode maps to a type AND exactly
one active firm matched) or leave the row pending for the Příchozí inbox.
"""
import sqlite3
from datetime import date

from repositories import prichozi_repo
from services import ingest_service, matching_service, pricing_service

# žádost mode → tracker úkon type for the AUTO-create path only. Modes not listed
# (notably 'zmena') never auto-create — they always wait in the inbox.
MODE_TO_TYP = {"prevod": "PŘEVOD", "zapis": "NOVÉ"}


def build_orv(serie: str | None, cislo: str | None) -> str | None:
    """ORV only when both halves are present (spec R6)."""
    s = (serie or "").strip()
    c = (cislo or "").strip()
    return f"{s}{c}".upper() if (s and c) else None


def context_note(payload: dict) -> str | None:
    """The automatic "z koho → na koho" transfer line, stored on the úkon's
    `prevod` column (kept separate from the user's poznámka).

    Prefers the provozovatel (operator) name on each side: when the owner is a
    leasing company, the operator is the real client we want named. Reads
    original → new (from → to)."""
    novy = (payload.get("novy_prov_jmeno") or payload.get("novy_jmeno") or "").strip()
    puvodni = (payload.get("puvodni_prov_jmeno") or payload.get("puvodni_jmeno") or "").strip()
    if novy and puvodni:
        return f"{puvodni} → {novy}"
    return novy or puvodni or None


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

    # Explicit assignment from zadosti's "Evidence úkonu" card: the user picked
    # the firm + type (+ price) up front, so we create the úkon exactly as chosen
    # — for ANY mode (incl. 'zmena') and any firm, no inbox sorting needed. When
    # absent we fall back to the original IČO auto-match below.
    explicit_firma_id = payload.get("firma_id")
    explicit_typ = (payload.get("typ_kod") or "").strip() or None

    # Prefer the provozovatel (operator) over the vlastník (owner): when a car's
    # owner is a leasing company, the operator is the client we actually track.
    m = matching_service.match_tiered(conn, [
        [payload.get("novy_prov_ico"), payload.get("puvodni_prov_ico")],  # operators first
        [payload.get("novy_ico"), payload.get("puvodni_ico")],            # owners fallback
    ])
    # Suggest the matched firm; if ambiguous, suggest the first match as a hint.
    # An explicit choice wins for the audit row's suggestion too.
    suggested = explicit_firma_id or m["firma_id"] or (m["matched"][0]["id"] if m["matched"] else None)

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
            puvodni_prov_jmeno=payload.get("puvodni_prov_jmeno"),
            puvodni_prov_ico=payload.get("puvodni_prov_ico"),
            novy_prov_jmeno=payload.get("novy_prov_jmeno"),
            novy_prov_ico=payload.get("novy_prov_ico"),
            suggested_firma_id=suggested,
            status="pending",
            raw=payload,
        )
    except sqlite3.IntegrityError:
        seen = prichozi_repo.get_by_zadost_id(conn, zadost_id)
        return {"status": "duplicate", "prichozi_id": seen["id"] if seen else None}

    # Decide the firm + type + price to create. Explicit choice first; else the
    # original auto-path (mode maps to a type AND exactly one active firm matched).
    if explicit_firma_id and explicit_typ:
        firma_id, typ = explicit_firma_id, explicit_typ
        celkem = payload.get("celkem")
        if celkem is None:
            celkem = pricing_service.effective_price(conn, firma_id, typ) or 0.0
    else:
        typ = MODE_TO_TYP.get(mode)
        firma_id = m["firma_id"] if typ else None
        celkem = pricing_service.effective_price(conn, firma_id, typ) or 0.0 if firma_id else 0.0

    if firma_id and typ:
        # Two SEPARATE fields: the user's typed note (poznamka) and the automatic
        # "z koho → na koho" transfer line (prevod). A typed note no longer erases
        # the parties — both are stored and shown independently.
        poznamka = (payload.get("poznamka") or "").strip() or None
        prevod = context_note(payload)
        try:
            uid = ingest_service.pridat_ukon(
                conn,
                firma_id=firma_id,
                datum=datum,
                typ_kod=typ,
                celkem=celkem,
                rz=rz, vin=vin, orv=orv,
                poznamka=poznamka,
                prevod=prevod,
                zdroj="zadosti",
                zpracoval=payload.get("profil"),  # who filled it out in zadosti
            )
        except ingest_service.IngestError:
            return {"status": "pending", "prichozi_id": pid}  # surfaces in inbox
        prichozi_repo.update(conn, pid, status="auto", created_ukon_id=uid)
        return {"status": "auto", "ukon_id": uid, "prichozi_id": pid}

    return {"status": "pending", "prichozi_id": pid}
