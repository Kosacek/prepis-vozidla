"""Which úkony a doklad (PPD) pays, computed on every read.

The old link was stored once, when žádosti pushed the doklad: a doklad that
arrived before its úkon (č. 180, 182) never got one, and a doklad for several
cars (č. 179) matched nothing. Here, in order:

1. explicit links (doklady issued from evidence, table ppd_ukony) — any date;
2. zadost_id → the úkon created from that žádost;
3. every RZ/VIN in the doklad's vozidlo text → úkony of that car dated within
   WINDOW_DAYS of the doklad (real data: −2 to +6 days); the nearest date wins,
   a same-day tie goes to the úkon whose price equals the doklad.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

WINDOW_DAYS = 14
_SPLIT = re.compile(r"[,;\r\n]+")


@dataclass(frozen=True)
class Links:
    by_doklad: dict[int, list[int]]   # číslo dokladu → úkony
    missing: dict[int, list[str]]     # číslo dokladu → auta bez úkonu
    firma: dict[int, int | None]      # číslo dokladu → firma
    by_ukon: dict[int, list[int]]     # úkon → čísla dokladů


def _key(value: str | None) -> str:
    return "".join((value or "").split()).upper()


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def vozidla(text: str | None) -> list[str]:
    """RZ/VIN items of a doklad's vozidlo text, in order, without duplicates."""
    out: list[str] = []
    for part in _SPLIT.split(text or ""):
        key = _key(part)
        if key and key not in out:
            out.append(key)
    return out


def set_explicit(conn, cislo: int, ukon_ids: list[int]) -> None:
    """Remember exactly which úkony a doklad issued from evidence pays."""
    with conn:
        conn.execute("DELETE FROM ppd_ukony WHERE ppd_cislo=?", (cislo,))
        conn.executemany("INSERT INTO ppd_ukony(ppd_cislo, ukon_id) VALUES(?, ?)",
                         [(cislo, uid) for uid in sorted(set(ukon_ids))])
    invalidate()


def _nearest(candidates: list, day: date, castka: int) -> list:
    distance = {u["id"]: abs((date.fromisoformat(u["datum"]) - day).days) for u in candidates}
    best = min(distance.values())
    tied = [u for u in candidates if distance[u["id"]] == best]
    if len(tied) > 1:
        same_price = [u for u in tied if round(u["celkem"] or 0) == castka]
        if len(same_price) == 1:
            return same_price
    return tied


def compute(conn) -> Links:
    ukony = {u["id"]: u for u in conn.execute(
        "SELECT id, firma_id, datum, rz, vin, celkem FROM ukony")}
    by_car: dict[str, list] = {}
    for u in ukony.values():
        for key in {_key(u["rz"]), _key(u["vin"])} - {""}:
            by_car.setdefault(key, []).append(u)
    explicit: dict[int, list[int]] = {}
    for row in conn.execute("SELECT ppd_cislo, ukon_id FROM ppd_ukony"):
        if row["ukon_id"] in ukony:
            explicit.setdefault(row["ppd_cislo"], []).append(row["ukon_id"])
    from_zadost = {row["zadost_id"]: row["created_ukon_id"] for row in conn.execute(
        "SELECT zadost_id, created_ukon_id FROM prichozi"
        " WHERE zadost_id IS NOT NULL AND created_ukon_id IS NOT NULL")}
    firma_by_ico = {_digits(f["ico"]): f["id"] for f in conn.execute(
        "SELECT id, ico FROM firmy WHERE ico IS NOT NULL AND ico != '' ORDER BY id DESC")}

    by_doklad: dict[int, list[int]] = {}
    missing: dict[int, list[str]] = {}
    firma: dict[int, int | None] = {}
    for d in conn.execute("SELECT cislo, datum, castka, vozidlo, zadost_id, prijato_ico"
                          " FROM ppd WHERE smazano=0"):
        cars = vozidla(d["vozidlo"])
        if d["cislo"] in explicit:
            linked = set(explicit[d["cislo"]])
        else:
            linked = set()
            uid = from_zadost.get(d["zadost_id"] or "")
            if uid in ukony:
                linked.add(uid)
            day = date.fromisoformat(d["datum"])
            for car in cars:
                near = [u for u in by_car.get(car, [])
                        if abs((date.fromisoformat(u["datum"]) - day).days) <= WINDOW_DAYS]
                if near:
                    linked.update(u["id"] for u in _nearest(near, day, d["castka"]))
        found_keys = {k for uid in linked for k in (_key(ukony[uid]["rz"]), _key(ukony[uid]["vin"]))}
        by_doklad[d["cislo"]] = sorted(linked)
        missing[d["cislo"]] = [car for car in cars if car not in found_keys]
        counts = Counter(ukony[uid]["firma_id"] for uid in linked)
        firma[d["cislo"]] = (max(counts, key=lambda f: (counts[f], -f)) if counts
                             else firma_by_ico.get(_digits(d["prijato_ico"])))

    by_ukon: dict[int, list[int]] = {}
    for cislo in sorted(by_doklad):
        for uid in by_doklad[cislo]:
            by_ukon.setdefault(uid, []).append(cislo)
    return Links(by_doklad, missing, firma, by_ukon)


def for_request() -> Links:
    """Links for the current request, computed at most once."""
    from flask import g
    import db
    if "ppd_links" not in g:
        g.ppd_links = compute(db.get_db())
    return g.ppd_links


def invalidate() -> None:
    from flask import g, has_app_context
    if has_app_context():
        g.pop("ppd_links", None)


def ukon_doklady(uid: int) -> list[int]:
    """Doklady paying úkon `uid` (Jinja global for the orange Zaplatit)."""
    return for_request().by_ukon.get(uid, [])
