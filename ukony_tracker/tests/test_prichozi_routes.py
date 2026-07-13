"""Příchozí inbox UI routes: render, approve, discard, nav badge."""
import pytest

import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, prichozi_repo, ukony_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="11111111")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
            pid = prichozi_repo.create(
                conn, zadost_id="z1", datum="2026-06-14", mode="prevod",
                rz="1AB2345", vin="TMBVIN1234567890", orv="ABC123456",
                novy_jmeno="Cardion", novy_ico="11111111",
                suggested_firma_id=fid, status="pending",
                raw={"znacka": "Škoda Octavia"},
            )
        yield c, fid, pid


def test_inbox_renders_pending(client):
    c, _, _ = client
    r = c.get("/prichozi")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Příchozí" in body and "1AB2345" in body and "ABC123456" in body
    assert "Cardion" in body                 # company name shown
    assert "Škoda Octavia" in body           # vehicle make from raw_json shown


def test_inbox_headlines_provozovatel_over_leasing_owner(client):
    """Leased car: the operator (provozovatel) is the headline party and the
    leasing-company owner is shown but demoted. Pins the new template branches."""
    c, _, _ = client
    with c.application.app_context():
        prichozi_repo.create(
            db.get_db(), zadost_id="lease-render", datum="2026-06-14", mode="zapis",
            rz="7SA5973", novy_jmeno="Raiffeisen-Leasing", novy_ico="22222222",
            novy_prov_jmeno="Jan Řidič", novy_prov_ico="11111111", status="pending",
        )
    body = c.get("/prichozi").get_data(as_text=True)
    assert "Jan Řidič" in body                 # operator name rendered…
    assert "nový provoz." in body              # …as the headline party
    assert "party-owner" in body               # owner demoted to the muted line
    assert "Raiffeisen-Leasing" in body        # owner still visible for reference


def test_inbox_migrates_legacy_prichozi_table(tmp_path, monkeypatch):
    """A prichozi table created before the prov_* columns existed must be upgraded
    in place by init_schema's _ensure_column backfill, and still render."""
    import sqlite3
    dbp = str(tmp_path / "legacy.db")
    # Build a pre-migration prichozi table (no prov_* columns) and seed a row.
    raw = sqlite3.connect(dbp)
    raw.executescript(
        "CREATE TABLE prichozi (id INTEGER PRIMARY KEY AUTOINCREMENT, zadost_id TEXT UNIQUE,"
        " received_at TEXT NOT NULL, datum TEXT, mode TEXT, rz TEXT, vin TEXT, orv TEXT,"
        " puvodni_jmeno TEXT, puvodni_ico TEXT, novy_jmeno TEXT, novy_ico TEXT,"
        " suggested_firma_id INTEGER, status TEXT NOT NULL DEFAULT 'pending',"
        " created_ukon_id INTEGER, raw_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
    )
    raw.execute(
        "INSERT INTO prichozi(zadost_id,received_at,datum,mode,novy_jmeno,status,created_at,updated_at)"
        " VALUES('legacy1','2026-06-01','2026-06-01','prevod','Old Owner','pending','2026-06-01','2026-06-01')"
    )
    raw.commit(); raw.close()

    monkeypatch.setattr(config, "DB_PATH", dbp)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            cols = [r[1] for r in db.get_db().execute("PRAGMA table_info(prichozi)")]
        assert "novy_prov_jmeno" in cols       # backfilled by the migration
        r = c.get("/prichozi")
        assert r.status_code == 200             # legacy row (NULL prov) still renders
        assert "Old Owner" in r.get_data(as_text=True)


def test_nav_badge_shows_pending_count(client):
    c, _, _ = client
    assert "nav-badge" in c.get("/prichozi").get_data(as_text=True)


def test_approve_creates_ukon(client):
    c, fid, pid = client
    r = c.post(f"/prichozi/{pid}/approve", data={
        "firma_id": str(fid), "typ_kod": "PŘEVOD", "celkem": "1300", "datum": "2026-06-14",
        "poznamka": "TZ + dobírka",
    })
    assert r.status_code in (302, 303)
    with c.application.app_context():
        conn = db.get_db()
        p = prichozi_repo.get(conn, pid)
        assert p["status"] == "approved"
        u = ukony_repo.get(conn, p["created_ukon_id"])
        assert u["firma_id"] == fid and u["typ_kod"] == "PŘEVOD" and u["celkem"] == 1300
        assert u["rz"] == "1AB2345" and u["orv"] == "ABC123456" and u["zdroj"] == "zadosti"
        assert u["poznamka"] == "TZ + dobírka"  # note from the form is saved
        assert u["prevod"] == "Cardion"         # auto transfer line stored separately


def test_approve_without_firma_keeps_pending(client):
    c, _, pid = client
    r = c.post(f"/prichozi/{pid}/approve", data={
        "firma_id": "", "typ_kod": "PŘEVOD", "celkem": "1300", "datum": "2026-06-14",
    })
    assert r.status_code in (302, 303)
    with c.application.app_context():
        assert prichozi_repo.get(db.get_db(), pid)["status"] == "pending"


def test_discard_marks_discarded(client):
    c, _, pid = client
    r = c.post(f"/prichozi/{pid}/discard")
    assert r.status_code in (302, 303)
    with c.application.app_context():
        assert prichozi_repo.get(db.get_db(), pid)["status"] == "discarded"
