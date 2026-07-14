"""Attribution: who added a car (zpracoval / config.PROFILY)."""
import pytest

import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ingest_service


@pytest.fixture
def client_fid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="11111111")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
        yield c, fid


# ── write path ────────────────────────────────────────────────────────────────

def test_pridat_ukon_stores_zpracoval(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        conn = db.get_db()
        uid = ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                                         typ_kod="PŘEVOD", celkem=1300, zpracoval="Roman")
        assert ukony_repo.get(conn, uid)["zpracoval"] == "Roman"


def test_pridat_ukon_blank_zpracoval_is_none(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        conn = db.get_db()
        uid = ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                                         typ_kod="PŘEVOD", celkem=1300, zpracoval="  ")
        assert ukony_repo.get(conn, uid)["zpracoval"] is None


# ── entry form ────────────────────────────────────────────────────────────────

def test_entry_add_records_and_carries_person(client_fid):
    c, fid = client_fid
    r = c.post(f"/ukony/{fid}", data={"datum": "2026-06-14", "typ_kod": "PŘEVOD",
                                      "celkem": "1300", "rz": "1AB2345", "mesic": "2026-06",
                                      "zpracoval": "Petr"})
    assert r.status_code in (302, 303)
    with c.application.app_context():
        rows = ukony_repo.list(db.get_db(), firma_id=fid)
    assert rows[0]["zpracoval"] == "Petr"
    assert "zpracoval=Petr" in r.headers["Location"]      # kept for the next car


def test_entry_form_offers_person_picker(client_fid):
    c, fid = client_fid
    body = c.get(f"/ukony/{fid}").get_data(as_text=True)
    assert 'name="zpracoval"' in body
    for p in config.PROFILY:
        assert f">{p}</option>" in body


# ── edit ──────────────────────────────────────────────────────────────────────

def test_edit_updates_person(client_fid):
    c, fid = client_fid
    with c.application.app_context():
        uid = ukony_repo.create(db.get_db(), firma_id=fid, datum="2026-06-14",
                                typ_kod="PŘEVOD", celkem=1300, zpracoval="David")
    c.post(f"/ukony/{uid}/upravit", data={"datum": "2026-06-14", "typ_kod": "PŘEVOD",
                                          "celkem": "1300", "zpracoval": "Roman", "back": "/"})
    with c.application.app_context():
        assert ukony_repo.get(db.get_db(), uid)["zpracoval"] == "Roman"


# ── display ───────────────────────────────────────────────────────────────────

def test_table_shows_kdo_badge(client_fid):
    # /ukony/vse uses the dashboard's header-less recent-row design; the
    # attribution renders as the kdo badge in the recent-kdo slot (before the price).
    c, fid = client_fid
    with c.application.app_context():
        ukony_repo.create(db.get_db(), firma_id=fid, datum="2026-06-14",
                          typ_kod="PŘEVOD", celkem=1300, rz="KDO111", zpracoval="David")
    body = c.get("/ukony/vse").get_data(as_text=True)
    assert 'class="recent-kdo"' in body                # badge slot in the row grid
    assert 'class="kdo"' in body and "David" in body   # attribution badge
