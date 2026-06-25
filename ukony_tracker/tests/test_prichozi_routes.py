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
