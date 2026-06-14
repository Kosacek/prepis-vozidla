"""Per-firm price overrides (firma_ceny). Sparse: a row exists only where a
firm's price for a type differs from the type's default."""
import sqlite3


def get_map(conn: sqlite3.Connection, firma_id: int) -> dict[str, float]:
    """Return {typ_kod: cena} of this firm's overrides (only the custom ones)."""
    rows = conn.execute(
        "SELECT typ_kod, cena FROM firma_ceny WHERE firma_id=?", (firma_id,)
    ).fetchall()
    return {r["typ_kod"]: r["cena"] for r in rows}


def get(conn: sqlite3.Connection, firma_id: int, typ_kod: str) -> float | None:
    r = conn.execute(
        "SELECT cena FROM firma_ceny WHERE firma_id=? AND typ_kod=?",
        (firma_id, typ_kod),
    ).fetchone()
    return r["cena"] if r else None


def set_price(conn: sqlite3.Connection, firma_id: int, typ_kod: str,
              cena: float | None) -> None:
    """Upsert an override; ``cena=None`` removes it (revert to the default)."""
    if cena is None:
        conn.execute(
            "DELETE FROM firma_ceny WHERE firma_id=? AND typ_kod=?",
            (firma_id, typ_kod),
        )
    else:
        conn.execute(
            "INSERT INTO firma_ceny(firma_id,typ_kod,cena) VALUES(?,?,?) "
            "ON CONFLICT(firma_id,typ_kod) DO UPDATE SET cena=excluded.cena",
            (firma_id, typ_kod, cena),
        )
    conn.commit()
