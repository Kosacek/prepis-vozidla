def test_schema_has_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"firmy", "typy_ukonu", "ukony"} <= names


def test_ukony_check_constraints(conn):
    conn.execute("INSERT INTO firmy(nazev,zkratka) VALUES('F','F')")
    fid = conn.execute("SELECT id FROM firmy").fetchone()["id"]
    import pytest, sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ukony(firma_id,datum,typ_kod,celkem,stav_platby,zaplaceno_kc,zdroj,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (fid, "2026-05-01", "PŘEVOD", -1, "nezaplaceno", 0, "rucni", "x", "x"))
