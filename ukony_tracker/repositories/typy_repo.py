import sqlite3


def upsert(
    conn: sqlite3.Connection,
    kod: str,
    vychozi_cena: float | None = None,
    poradi: int = 0,
    aktivni: int = 1,
) -> None:
    conn.execute(
        "INSERT INTO typy_ukonu(kod,vychozi_cena,poradi,aktivni) VALUES(?,?,?,?)"
        " ON CONFLICT(kod) DO UPDATE SET vychozi_cena=excluded.vychozi_cena,"
        " poradi=excluded.poradi, aktivni=excluded.aktivni",
        (kod, vychozi_cena, poradi, aktivni),
    )
    conn.commit()


def get_by_kod(conn: sqlite3.Connection, kod: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM typy_ukonu WHERE kod=?", (kod,)
    ).fetchone()


def list_active(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM typy_ukonu WHERE aktivni=1 ORDER BY poradi, kod"
    ).fetchall()


def list_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM typy_ukonu ORDER BY poradi, kod"
    ).fetchall()
