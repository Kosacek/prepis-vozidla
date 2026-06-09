import pytest
import app as appmod
import db
import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            from repositories import firmy_repo
            firmy_repo.create(db.get_db(), nazev="Cardion", zkratka="Cardion", ico="04156854")
        yield c


def test_api_creates_by_ico(client):
    r = client.post(
        "/api/ukony",
        json={
            "ico": "04156854",
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": 1300,
            "zdroj": "prepis_app",
        },
    )
    assert r.status_code == 201


def test_api_unknown_firma_400(client):
    r = client.post(
        "/api/ukony",
        json={
            "ico": "99999999",
            "datum": "2026-05-04",
            "typ_kod": "PŘEVOD",
            "celkem": 1300,
        },
    )
    assert r.status_code == 400
