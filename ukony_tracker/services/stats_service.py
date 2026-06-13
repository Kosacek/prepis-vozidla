"""Aggregation queries for the dashboard and reports."""
from sqlite3 import Connection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _period_clause(year: int, month: int | None) -> tuple[str, str]:
    """Return (WHERE fragment, bind value) for the given period."""
    if month:
        return "substr(datum,1,7)=?", f"{year:04d}-{month:02d}"
    return "substr(datum,1,4)=?", f"{year:04d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mesicni_souhrn(conn: Connection, year: int, month: int) -> dict:
    """Return total count and revenue for a single calendar month."""
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(celkem),0) s FROM ukony "
        "WHERE substr(datum,1,7)=?",
        (f"{year:04d}-{month:02d}",),
    ).fetchone()
    return {"pocet": r["n"], "trzby": r["s"]}


def rocni_souhrn(conn: Connection, year: int) -> dict:
    """Return total count and revenue for a full calendar year."""
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(celkem),0) s FROM ukony "
        "WHERE substr(datum,1,4)=?",
        (f"{year:04d}",),
    ).fetchone()
    return {"pocet": r["n"], "trzby": r["s"]}


def rocni_trend(conn: Connection, year: int) -> list[dict]:
    """Return a 12-element list (one entry per month) with pocet and trzby."""
    rows = conn.execute(
        "SELECT substr(datum,6,2) m, COUNT(*) n, COALESCE(SUM(celkem),0) s "
        "FROM ukony WHERE substr(datum,1,4)=? GROUP BY m",
        (f"{year:04d}",),
    ).fetchall()
    by_month = {r["m"]: (r["n"], r["s"]) for r in rows}
    out: list[dict] = []
    for mo in range(1, 13):
        n, s = by_month.get(f"{mo:02d}", (0, 0))
        out.append({"month": mo, "pocet": n, "trzby": s})
    return out


def podle_firmy(conn: Connection, year: int, month: int | None = None) -> list:
    """Revenue and count per firma for the given period, ordered by revenue desc."""
    cl, arg = _period_clause(year, month)
    return conn.execute(
        f"SELECT f.zkratka, COUNT(*) pocet, COALESCE(SUM(u.celkem),0) trzby "
        f"FROM ukony u JOIN firmy f ON f.id=u.firma_id WHERE {cl} "
        f"GROUP BY f.id ORDER BY trzby DESC",
        (arg,),
    ).fetchall()


def podle_typu(conn: Connection, year: int, month: int | None = None) -> list:
    """Revenue and count per úkon type for the given period, ordered by count desc."""
    cl, arg = _period_clause(year, month)
    return conn.execute(
        f"SELECT typ_kod, COUNT(*) pocet, COALESCE(SUM(celkem),0) trzby "
        f"FROM ukony WHERE {cl} GROUP BY typ_kod ORDER BY pocet DESC",
        (arg,),
    ).fetchall()


def nezaplaceno_celkem(conn: Connection) -> float:
    """Return the total outstanding balance across all úkony (celkem - zaplaceno_kc)."""
    r = conn.execute(
        "SELECT COALESCE(SUM(celkem - zaplaceno_kc),0) d FROM ukony"
    ).fetchone()
    return r["d"]


def rocni_trend_podle_firmy(conn: Connection, year: int) -> list:
    """Per-firm monthly úkon counts for the year, for comparing firms on a line
    chart. Returns list of {zkratka, pocty: [12 ints]}, ordered by total desc."""
    rows = conn.execute(
        "SELECT f.zkratka, substr(u.datum,6,2) m, COUNT(*) n "
        "FROM ukony u JOIN firmy f ON f.id=u.firma_id "
        "WHERE substr(u.datum,1,4)=? GROUP BY f.id, m",
        (f"{year:04d}",),
    ).fetchall()
    by_firma: dict[str, list[int]] = {}
    for r in rows:
        arr = by_firma.setdefault(r["zkratka"], [0] * 12)
        arr[int(r["m"]) - 1] = r["n"]
    out = [{"zkratka": z, "pocty": p} for z, p in by_firma.items()]
    out.sort(key=lambda x: sum(x["pocty"]), reverse=True)
    return out


def denni_souhrn(conn: Connection, iso_date: str) -> dict:
    """Count and revenue for a single day (ISO date string)."""
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(celkem),0) s FROM ukony WHERE datum=?",
        (iso_date,),
    ).fetchone()
    return {"pocet": r["n"], "trzby": r["s"]}


def nezaplaceno_podle_firmy(conn: Connection) -> list:
    """Outstanding balance per firm (only firms that are owed something),
    ordered by debt descending. Rows: firma_id, zkratka, pocet, dluh."""
    return conn.execute(
        "SELECT f.id firma_id, f.zkratka, COUNT(*) pocet, "
        "SUM(u.celkem - u.zaplaceno_kc) dluh "
        "FROM ukony u JOIN firmy f ON f.id=u.firma_id "
        "WHERE u.celkem > u.zaplaceno_kc "
        "GROUP BY f.id ORDER BY dluh DESC",
    ).fetchall()
