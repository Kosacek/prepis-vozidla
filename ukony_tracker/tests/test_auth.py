import pytest
import app as appmod
import config


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret123")
    a = appmod.create_app()
    a.testing = True
    return a.test_client()


def test_healthz_open_when_gated(gated_client):
    assert gated_client.get("/healthz").status_code == 200


def test_dashboard_redirects_when_not_logged_in(gated_client):
    r = gated_client.get("/")
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]


def test_login_then_choose_profile_grants_access(gated_client):
    assert gated_client.post("/login", data={"heslo": "secret123"}).status_code in (301, 302)
    # logged in but must pick who's working first
    r = gated_client.get("/")
    assert r.status_code in (301, 302) and "/kdo" in r.headers["Location"]
    gated_client.post("/kdo", data={"profil": "Roman"})
    assert gated_client.get("/").status_code == 200


def test_login_wrong_password_denied(gated_client):
    gated_client.post("/login", data={"heslo": "nope"})
    r = gated_client.get("/")
    assert r.status_code in (301, 302) and "/login" in r.headers["Location"]
