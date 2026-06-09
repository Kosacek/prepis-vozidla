import pytest
import app as appmod
import db
import config
from repositories import firmy_repo, typy_repo, ukony_repo


@pytest.fixture
def client_fid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
        yield c, fid


def test_entry_page_renders(client_fid):
    c, fid = client_fid
    r = c.get(f"/ukony/{fid}")
    assert r.status_code == 200
    assert "Nový úkon" in r.get_data(as_text=True)


def test_post_creates_ukon(client_fid):
    c, fid = client_fid
    r = c.post(
        f"/ukony/{fid}",
        data={
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": "1300",
            "rz": "3BP3552",
            "mesic": "2026-05",
        },
    )
    assert r.status_code in (302, 303)
    with c.application.app_context():
        rows = ukony_repo.list(db.get_db(), firma_id=fid)
    assert len(rows) == 1 and rows[0]["rz"] == "3BP3552"
