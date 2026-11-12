"""Payment of a faktura (invoice by bank transfer).

A faktura never marks its úkony paid when it is issued — they stay unpaid and
linked to it until the money arrives. `oznac_fakturu_zaplacenou` is the one
function that settles it; a later Moneta payment matcher will call it (no
route yet). It is idempotent: a second call changes nothing.
"""
from __future__ import annotations

import db
from repositories import ppd_repo, ukony_repo
from services import ingest_service as ing
from services import ppd_links


def oznac_fakturu_zaplacenou(cislo: int, datum: str | None = None, conn=None) -> int:
    """Mark the úkony linked to faktura `cislo` paid; returns how many were
    newly marked. `datum` (ISO or dd.mm.yyyy, default today) is remembered as
    the day the payment arrived, the first time only. Unknown numbers,
    deleted doklady and PPDs are left alone (returns 0)."""
    conn = conn or db.get_db()
    doklad = ppd_repo.get_by_cislo(conn, cislo)
    if doklad is None or doklad["druh"] != "faktura" or doklad["smazano"]:
        return 0
    day = ppd_repo._iso_date(datum, "Datum platby") if datum else db.now_iso()[:10]
    marked = 0
    for uid in ppd_links.compute(conn).by_doklad.get(cislo, []):
        u = ukony_repo.get(conn, uid)
        if u is None or u["stav_platby"] == "zaplaceno":
            continue
        celkem = float(u["celkem"] or 0)
        stav = ing.derive_stav(celkem, celkem)
        if stav == u["stav_platby"]:
            continue
        ukony_repo.update(conn, uid, zaplaceno_kc=celkem, stav_platby=stav)
        marked += 1
    with conn:
        conn.execute("UPDATE ppd SET zaplaceno_dne=? WHERE cislo=? AND zaplaceno_dne IS NULL", (day, cislo))
    ppd_links.invalidate()
    return marked
