"""Effective úkon price = firm override (firma_ceny) → else the type's default
(typy_ukonu.vychozi_cena) → else None. The úkon's ``celkem`` stays the source of
truth; these values only PREFILL the price when adding/approving an úkon."""
from sqlite3 import Connection

from repositories import firma_ceny_repo, typy_repo


def effective_price(conn: Connection, firma_id: int, typ_kod: str) -> float | None:
    """The price to suggest for (firma, typ): firm override, else type default."""
    override = firma_ceny_repo.get(conn, firma_id, typ_kod)
    if override is not None:
        return override
    t = typy_repo.get_by_kod(conn, typ_kod)
    if t and t["vychozi_cena"] is not None:
        return float(t["vychozi_cena"])
    return None


def firm_price_map(conn: Connection, firma_id: int) -> dict[str, float | None]:
    """{typ_kod: effective_price} across all ACTIVE types, for this firm — used
    to prefill the entry form's type buttons with this firm's prices."""
    overrides = firma_ceny_repo.get_map(conn, firma_id)
    out: dict[str, float | None] = {}
    for t in typy_repo.list_active(conn):
        if t["kod"] in overrides:
            out[t["kod"]] = overrides[t["kod"]]
        elif t["vychozi_cena"] is not None:
            out[t["kod"]] = float(t["vychozi_cena"])
        else:
            out[t["kod"]] = None
    return out
