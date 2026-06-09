import sqlite3

import db


def create(
    conn: sqlite3.Connection,
    *,
    firma_id: int,
    datum: str,
    typ_kod: str,
    celkem: float,
    rz: str | None = None,
    vin: str | None = None,
    poznamka: str | None = None,
    stav_platby: str = "nezaplaceno",
    zaplaceno_kc: float = 0,
    zdroj: str = "rucni",
) -> int:
    ts = db.now_iso()
    cur = conn.execute(
        "INSERT INTO ukony(firma_id,datum,rz,typ_kod,celkem,vin,poznamka,"
        "stav_platby,zaplaceno_kc,zdroj,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (firma_id, datum, rz, typ_kod, celkem, vin, poznamka,
         stav_platby, zaplaceno_kc, zdroj, ts, ts),
    )
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, uid: int, **fields) -> None:
    fields["updated_at"] = db.now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE ukony SET {cols} WHERE id=?", (*fields.values(), uid))
    conn.commit()


def get(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ukony WHERE id=?", (uid,)).fetchone()


def delete(conn: sqlite3.Connection, uid: int) -> None:
    conn.execute("DELETE FROM ukony WHERE id=?", (uid,))
    conn.commit()


def list(
    conn: sqlite3.Connection,
    *,
    firma_id: int | None = None,
    year: int | None = None,
    month: int | None = None,
    typ_kod: str | None = None,
    stav: str | None = None,
) -> list[sqlite3.Row]:
    q = [
        "SELECT u.*, f.zkratka AS firma_zkratka"
        " FROM ukony u JOIN firmy f ON f.id=u.firma_id"
    ]
    where: list[str] = []
    args: list = []

    if firma_id is not None:
        where.append("u.firma_id=?")
        args.append(firma_id)
    if typ_kod:
        where.append("u.typ_kod=?")
        args.append(typ_kod)
    if stav:
        where.append("u.stav_platby=?")
        args.append(stav)
    if year and month:
        where.append("substr(u.datum,1,7)=?")
        args.append(f"{year:04d}-{month:02d}")
    elif year:
        where.append("substr(u.datum,1,4)=?")
        args.append(f"{year:04d}")

    if where:
        q.append("WHERE " + " AND ".join(where))
    q.append("ORDER BY u.datum DESC, u.id DESC")

    return conn.execute(" ".join(q), args).fetchall()
