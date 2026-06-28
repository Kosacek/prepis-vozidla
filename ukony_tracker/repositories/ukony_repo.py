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
    orv: str | None = None,
    poznamka: str | None = None,
    stav_platby: str = "nezaplaceno",
    zaplaceno_kc: float = 0,
    zdroj: str = "rucni",
) -> int:
    ts = db.now_iso()
    cur = conn.execute(
        "INSERT INTO ukony(firma_id,datum,rz,typ_kod,celkem,vin,orv,poznamka,"
        "stav_platby,zaplaceno_kc,zdroj,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (firma_id, datum, rz, typ_kod, celkem, vin, orv, poznamka,
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


def count_by_firma(conn: sqlite3.Connection, firma_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM ukony WHERE firma_id=?", (firma_id,)
    ).fetchone()["n"]


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


def search(conn: sqlite3.Connection, q: str, limit: int = 25) -> list[sqlite3.Row]:
    """Free-text search across all úkony for the dashboard quick-find: matches a
    substring of RZ, VIN, ORV, poznámka, or firm shortcut. Used to locate a car
    (e.g. by a few VIN digits) so its úkon can be opened and the SPZ filled in.

    Returns newest-first, capped at ``limit``. Empty/blank query → no rows.
    """
    term = (q or "").strip()
    if not term:
        return []
    like = f"%{term}%"
    return conn.execute(
        "SELECT u.*, f.zkratka AS firma_zkratka"
        " FROM ukony u JOIN firmy f ON f.id=u.firma_id"
        " WHERE u.rz LIKE ? OR u.vin LIKE ? OR u.orv LIKE ?"
        "    OR u.poznamka LIKE ? OR f.zkratka LIKE ?"
        " ORDER BY u.datum DESC, u.id DESC LIMIT ?",
        (like, like, like, like, like, limit),
    ).fetchall()
