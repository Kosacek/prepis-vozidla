"""Uložení PPD ze zadosti a souhrny pro budoucího asistenta na /zeptej."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import db

_MAX_INT = 2**63 - 1  # Rozsah INTEGER v SQLite.
_TEXT_FIELDS = ("prijato_od", "prijato_ico", "ucel", "vozidlo", "zadost_id")


def _normalize(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ValueError("Doklad musí být JSON objekt.")
    cislo = record.get("cislo")
    if type(cislo) is not int or not -_MAX_INT - 1 <= cislo <= _MAX_INT:
        raise ValueError("Číslo dokladu musí být celé číslo v rozsahu SQLite INTEGER.")
    castka = record.get("castka")
    if type(castka) is not int or not 0 <= castka <= _MAX_INT:
        raise ValueError("Částka musí být celé číslo ≥ 0 v rozsahu SQLite INTEGER.")
    datum = record.get("datum")
    if not isinstance(datum, str):
        raise ValueError("Datum musí být platné datum DD.MM.YYYY nebo YYYY-MM-DD.")
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            datum = datetime.strptime(datum.strip(), fmt).date().isoformat()
            break
        except ValueError:
            pass
    else:
        raise ValueError("Datum musí být platné datum DD.MM.YYYY nebo YYYY-MM-DD.")

    values = {"cislo": cislo, "datum": datum, "castka": castka}
    for field in _TEXT_FIELDS:
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Pole {field} musí být text.")
        values[field] = (value or "").strip().upper()
    smazano = record.get("smazano", False)
    if type(smazano) is not bool:
        raise ValueError("Pole smazano musí být boolean.")
    values["smazano"] = int(smazano)
    return values


def _vehicle_key(value: str | None) -> str:
    # Ignorujeme i mezery uvnitř RZ/VIN, tabulátory a pevné mezery.
    return "".join((value or "").split()).upper()


def _find_ukon(conn: sqlite3.Connection, values: dict, zadost_id: str) -> int | None:
    if zadost_id:
        # Externí ID hledáme přesně v původní velikosti písmen, ještě před
        # normalizací uloženého textu PPD. Různá ID nesmí spojit cizí doklad.
        incoming = conn.execute(
            "SELECT created_ukon_id FROM prichozi"
            " WHERE zadost_id=? AND created_ukon_id IS NOT NULL",
            (zadost_id,),
        ).fetchone()
        if incoming:
            return incoming["created_ukon_id"]

    vehicle = _vehicle_key(values["vozidlo"])
    if not vehicle:
        return None
    match = None
    for row in conn.execute(
        "SELECT id, rz, vin FROM ukony"
        " WHERE datum BETWEEN date(?, '-7 days') AND date(?, '+7 days')",
        (values["datum"], values["datum"]),
    ):
        if vehicle in (_vehicle_key(row["rz"]), _vehicle_key(row["vin"])):
            if match is not None:
                return None  # Dva úkony na stejné vozidlo nelze bezpečně rozlišit.
            match = row["id"]
    return match


def upsert(conn: sqlite3.Connection, record: dict) -> tuple[sqlite3.Row, bool]:
    """Uloží celý doklad podle čísla; opakovaný stejný push nezmění ani timestamp.

    Neplatný záznam vyvolá ValueError. Každý doklad má vlastní transakci, aby
    chybný řádek při importu nevrátil zpět dříve úspěšně uložené doklady.
    """
    values = _normalize(record)
    zadost_id = (record.get("zadost_id") or "").strip()
    with conn:
        values["ukon_id"] = _find_ukon(conn, values, zadost_id)
        ts = db.now_iso()
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        cur = conn.execute(
            f"INSERT INTO ppd({columns},created_at,updated_at)"
            f" VALUES({placeholders},?,?) ON CONFLICT(cislo) DO NOTHING",
            (*values.values(), ts, ts),
        )
        created = cur.rowcount == 1
        if not created:
            existing = get_by_cislo(conn, values["cislo"])
            if values["ukon_id"] is None:
                values["ukon_id"] = existing["ukon_id"]
            if any(existing[key] != value for key, value in values.items()):
                # Názvy sloupců pochází pouze z našeho pevného seznamu polí.
                setters = ",".join(f"{key}=?" for key in values)
                conn.execute(
                    f"UPDATE ppd SET {setters},updated_at=? WHERE cislo=?",
                    (*values.values(), ts, values["cislo"]),
                )
        row = get_by_cislo(conn, values["cislo"])
    return row, created


def get_by_cislo(conn: sqlite3.Connection, cislo: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ppd WHERE cislo=?", (cislo,)).fetchone()


def _filters(od, do, q, include_deleted) -> tuple[str, list]:
    where, args = [], []
    if not include_deleted:
        where.append("smazano=0")
    if od:
        where.append("datum>=?")
        args.append(od)
    if do:
        where.append("datum<=?")
        args.append(do)
    term = (q or "").strip().upper()
    if term:
        # Uložené texty jsou velkými písmeny i s českou diakritikou.
        # INSTR hledá doslovný text; % a _ v dotazu nejsou SQL zástupné znaky.
        where.append(
            "(instr(prijato_od,?)>0 OR instr(vozidlo,?)>0"
            " OR instr(CAST(cislo AS TEXT),?)>0)"
        )
        args.extend((term, term, term))
    return (" WHERE " + " AND ".join(where) if where else ""), args


def list(
    conn: sqlite3.Connection,
    od: str | None = None,
    do: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int | None = 500,
) -> list[sqlite3.Row]:
    """Doklady od nejnovějšího data; meze období jsou včetně obou dnů."""
    where, args = _filters(od, do, q, include_deleted)
    sql = "SELECT * FROM ppd" + where + " ORDER BY datum DESC, cislo DESC"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return conn.execute(sql, args).fetchall()


def totals(
    conn: sqlite3.Connection,
    od: str | None,
    do: str | None,
    *,
    q: str | None = None,
    include_deleted: bool = False,
) -> dict:
    """Počet a součet Kč za období, včetně mezí; standardně bez smazaných PPD.

    Podklad pro budoucího AI asistenta na /zeptej. PPD jsou příjmy hotovosti,
    nikoli ceny úkonů; součet se nesmí přičítat k ukony.celkem jako další tržby.
    Výsledek není omezen limitem seznamu; q a include_deleted slouží i stránce
    Doklady, aby její souhrn odpovídal celému filtru.
    """
    where, args = _filters(od, do, q, include_deleted)
    row = conn.execute(
        "SELECT COUNT(*) pocet, COALESCE(SUM(castka),0) castka FROM ppd" + where,
        args,
    ).fetchone()
    return dict(row)
