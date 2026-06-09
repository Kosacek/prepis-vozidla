import sqlite3


def create(
    conn: sqlite3.Connection,
    *,
    nazev: str,
    zkratka: str,
    ico: str | None = None,
    adresa: str | None = None,
    psc: str | None = None,
    aktivni: int = 1,
    poradi: int = 0,
    legacy_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO firmy(nazev,zkratka,ico,adresa,psc,aktivni,poradi,legacy_id)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (nazev, zkratka, ico, adresa, psc, aktivni, poradi, legacy_id),
    )
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, fid: int, **fields) -> None:
    if not fields:
        return  # no-op edit: avoid building malformed "UPDATE firmy SET  WHERE id=?"
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE firmy SET {cols} WHERE id=?", (*fields.values(), fid))
    conn.commit()


def get(conn: sqlite3.Connection, fid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM firmy WHERE id=?", (fid,)).fetchone()


def get_by_ico(conn: sqlite3.Connection, ico: str | None) -> sqlite3.Row | None:
    if not ico:
        return None
    return conn.execute("SELECT * FROM firmy WHERE ico=?", (ico,)).fetchone()


def list_all(conn: sqlite3.Connection, only_active: bool = False) -> list[sqlite3.Row]:
    q = "SELECT * FROM firmy"
    if only_active:
        q += " WHERE aktivni=1"
    q += " ORDER BY poradi, nazev"
    return conn.execute(q).fetchall()
