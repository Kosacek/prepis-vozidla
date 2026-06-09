import pytest

import app as appmod
import db
import config
from repositories import firmy_repo
from services import ingest_service as ing


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    return a


def test_delete_empty_firma_is_removed(app):
    with app.app_context():
        fid = firmy_repo.create(db.get_db(), nazev="Smazat mě", zkratka="SM")
    r = app.test_client().post(f"/firmy/{fid}/smazat")
    assert r.status_code in (302, 303)
    with app.app_context():
        assert firmy_repo.get(db.get_db(), fid) is None


def test_delete_firma_with_ukony_is_blocked(app):
    with app.app_context():
        fid = firmy_repo.create(db.get_db(), nazev="Má úkon", zkratka="MU", ico="111")
        ing.pridat_ukon(db.get_db(), firma_id=fid, datum="2026-05-01",
                        typ_kod="PŘEVOD", celkem=1300)
    r = app.test_client().post(f"/firmy/{fid}/smazat")
    assert r.status_code in (302, 303)
    with app.app_context():
        assert firmy_repo.get(db.get_db(), fid) is not None  # must NOT be deleted
