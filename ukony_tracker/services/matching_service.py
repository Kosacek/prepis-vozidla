"""Resolve žádost party IČO(s) to a tracker client firm.

Used by the žádost intake to decide auto-create vs. inbox. Matching is exact on
the digit-normalized IČO, against ACTIVE firms only, and de-duplicated on the
resolved firma_id (so the same firm appearing on two parties is one match, while
two different firms are ambiguous).
"""
import re
from sqlite3 import Connection

from repositories import firmy_repo


def normalize_ico(ico: str | None) -> str | None:
    """Strip everything but digits; return None for empty/None."""
    if not ico:
        return None
    digits = re.sub(r"\D", "", str(ico))
    return digits or None


def match(conn: Connection, icos: list[str | None]) -> dict:
    """Resolve candidate IČOs to active firms.

    Returns ``{"firma_id": int | None, "matched": [Row], "ambiguous": bool}``:
    - exactly one distinct active firm matched → ``firma_id`` set, not ambiguous
    - none matched → ``firma_id`` None, not ambiguous
    - two or more distinct firms matched → ``firma_id`` None, ``ambiguous`` True
    """
    active_by_ico: dict[str, "Row"] = {}
    for f in firmy_repo.list_all(conn, only_active=True):
        ni = normalize_ico(f["ico"])
        if ni:
            active_by_ico.setdefault(ni, f)  # first firm wins on duplicate IČO

    matched: dict[int, "Row"] = {}
    for ico in icos:
        ni = normalize_ico(ico)
        if ni and ni in active_by_ico:
            f = active_by_ico[ni]
            matched[f["id"]] = f

    rows = list(matched.values())
    if len(rows) == 1:
        return {"firma_id": rows[0]["id"], "matched": rows, "ambiguous": False}
    return {"firma_id": None, "matched": rows, "ambiguous": len(rows) > 1}


def match_tiered(conn: Connection, tiers: list[list[str | None]]) -> dict:
    """Match by priority tiers. The FIRST tier that yields any match decides
    (one distinct firm → match, ≥2 → ambiguous); later tiers are ignored.

    Used so the provozovatel (operator) wins over the vlastník (owner): when a
    car's owner is a leasing company but the operator is the actual client, we
    track the operator. Pass operator IČOs as tier 0, owner IČOs as tier 1.
    """
    for icos in tiers:
        m = match(conn, icos)
        if m["matched"]:
            return m
    return {"firma_id": None, "matched": [], "ambiguous": False}
