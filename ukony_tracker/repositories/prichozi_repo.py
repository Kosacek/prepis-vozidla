"""Storage for incoming žádosti (the Příchozí inbox)."""
import json
import sqlite3

import db


def create(
    conn: sqlite3.Connection,
    *,
    zadost_id: str | None,
    datum: str | None,
    mode: str | None,
    rz: str | None = None,
    vin: str | None = None,
    orv: str | None = None,
    puvodni_jmeno: str | None = None,
    puvodni_ico: str | None = None,
    novy_jmeno: str | None = None,
    novy_ico: str | None = None,
    puvodni_prov_jmeno: str | None = None,
    puvodni_prov_ico: str | None = None,
    novy_prov_jmeno: str | None = None,
    novy_prov_ico: str | None = None,
    suggested_firma_id: int | None = None,
    status: str = "pending",
    raw: dict | None = None,
) -> int:
    """Insert an incoming žádost. Raises sqlite3.IntegrityError if zadost_id is a
    duplicate (the UNIQUE constraint is the idempotency backstop)."""
    ts = db.now_iso()
    cur = conn.execute(
        "INSERT INTO prichozi(zadost_id,received_at,datum,mode,rz,vin,orv,"
        "puvodni_jmeno,puvodni_ico,novy_jmeno,novy_ico,"
        "puvodni_prov_jmeno,puvodni_prov_ico,novy_prov_jmeno,novy_prov_ico,"
        "suggested_firma_id,status,raw_json,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (zadost_id, ts, datum, mode, rz, vin, orv,
         puvodni_jmeno, puvodni_ico, novy_jmeno, novy_ico,
         puvodni_prov_jmeno, puvodni_prov_ico, novy_prov_jmeno, novy_prov_ico,
         suggested_firma_id, status, json.dumps(raw or {}, ensure_ascii=False), ts, ts),
    )
    conn.commit()
    return cur.lastrowid


def get(conn: sqlite3.Connection, pid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM prichozi WHERE id=?", (pid,)).fetchone()


def get_by_zadost_id(conn: sqlite3.Connection, zadost_id: str) -> sqlite3.Row | None:
    if not zadost_id:
        return None
    return conn.execute(
        "SELECT * FROM prichozi WHERE zadost_id=?", (zadost_id,)
    ).fetchone()


def list_by_status(conn: sqlite3.Connection, status: str = "pending") -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM prichozi WHERE status=? ORDER BY received_at DESC, id DESC",
        (status,),
    ).fetchall()


def count_pending(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM prichozi WHERE status='pending'"
    ).fetchone()["n"]


def update(conn: sqlite3.Connection, pid: int, **fields) -> None:
    fields["updated_at"] = db.now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE prichozi SET {cols} WHERE id=?", (*fields.values(), pid))
    conn.commit()
