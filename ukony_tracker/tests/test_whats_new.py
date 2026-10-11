"""The "Co je nového" popup + the "Nová verze aplikace" bar.

The popup announces what changed, once per device; the bar tells a page
left open that the server now runs newer code. Both must only ever reach
people who are logged in.
"""
import pytest

import app as appmod
import config

RELEASE_KEY = "evidence_whatsnew_ai-hledani-technicak"


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret123")
    a = appmod.create_app()
    a.testing = True
    return a.test_client()


def _login(client):
    client.post("/login", data={"heslo": "secret123"})


def test_popup_is_on_pages_for_logged_in_people(gated_client):
    _login(gated_client)
    html = gated_client.get("/").get_data(as_text=True)
    assert RELEASE_KEY in html
    assert "Rozumím" in html
    assert "Zeptej se" in html and "Techničák" in html


def test_popup_never_on_the_login_page(gated_client):
    html = gated_client.get("/login").get_data(as_text=True)
    assert RELEASE_KEY not in html
    assert "Nová verze aplikace" not in html


def test_build_endpoint_reports_the_running_code(gated_client):
    _login(gated_client)
    r = gated_client.get("/verze")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    build = r.get_json()["build"]
    assert isinstance(build, str) and len(build) >= 8
    assert gated_client.get("/verze").get_json()["build"] == build


def test_pages_are_stamped_with_the_build_that_drew_them(gated_client):
    _login(gated_client)
    build = gated_client.get("/verze").get_json()["build"]
    html = gated_client.get("/").get_data(as_text=True)
    assert f'var pageBuild = "{build}";' in html
    assert "Nová verze aplikace" in html


def test_build_endpoint_needs_login(gated_client):
    r = gated_client.get("/verze")
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]
