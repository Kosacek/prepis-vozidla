"""The "Co je nového" popup + the "Nová verze aplikace" bar.

The popup announces what changed, once per device; the bar tells a page
left open that the server now runs newer code. Both must only ever reach
people who are logged in.
"""
import pytest

import app as appmod
import config
import novinky
from releases import CURRENT_VERSION, RELEASES

RELEASE_KEY = "evidence_whatsnew_"


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


def test_releases_are_newest_first_and_well_formed():
    versions = [r.version for r in RELEASES]
    assert len(set(versions)) == len(versions)
    dates = [r.date for r in RELEASES]
    assert dates == sorted(dates, reverse=True)
    for r in RELEASES:
        assert r.title and 1 <= len(r.points) <= 2
    assert CURRENT_VERSION == RELEASES[0].version


def test_version_button_opens_the_sheet(gated_client):
    _login(gated_client)
    html = gated_client.get("/").get_data(as_text=True)
    assert f"v{CURRENT_VERSION}" in html and "data-releases-open" in html
    assert "Co umí Evidence" in html
    # The old step-through browser is gone.
    assert "Starší" not in html and "Novější" not in html


def test_popup_is_the_newest_release(gated_client):
    _login(gated_client)
    html = gated_client.get("/").get_data(as_text=True)
    assert f"{RELEASE_KEY}{CURRENT_VERSION}" in html
    intro = html[html.index('id="nvIntro"'):]
    assert RELEASES[0].title in intro[:1500]
    assert RELEASES[0].points[0] in html


def test_sheet_shows_each_current_release_exactly_once(gated_client):
    _login(gated_client)
    html = gated_client.get("/").get_data(as_text=True)
    for r in novinky.aktualni():
        assert html.count(f'class="nv-fe') >= 1
        assert html.count(f'data-version="{r.version}"') == 1, r.version
    assert 'is-new" data-version="%s"' % CURRENT_VERSION in html


def test_superseded_and_obsolete_releases_never_appear(gated_client):
    _login(gated_client)
    html = gated_client.get("/").get_data(as_text=True)
    live = {r.version for r in novinky.aktualni()}
    hidden = {v for v, _ in novinky.skryte()}
    assert hidden and not (live & hidden)
    for v in hidden:
        assert f'data-version="{v}"' not in html, v
    # 2.9 introduced Hotově/Převodem, 2.9.1 removed it.
    assert "2.9" in hidden and "Hotově" not in html.split('id="nvSheet"')[1].split('id="nvIntro"')[0]


def test_every_release_is_classified():
    versions = {r.version for r in RELEASES}
    for r in RELEASES:
        assert set(r.nahrazuje) <= versions
        if r.oblast:
            assert r.oblast in dict(novinky.SEKCE)
            assert r.nazev and r.radek
        # Anything not shown is either replaced or marked obsolete.
        assert r.version in {v for v, _ in novinky.skryte()} or r.oblast
    assert RELEASES[0].oblast and not RELEASES[0].zastarale


def test_sections_are_a_few_and_ordered():
    s = novinky.sekce(CURRENT_VERSION)
    assert 4 <= len(s) <= 6
    assert [x["key"] for x in s] == [k for k, _ in novinky.SEKCE if k in {x["key"] for x in s}]
    for sec in s:
        versions = [k["version"] for k in sec["karty"]]
        assert versions == sorted(versions, key=novinky._klic, reverse=True)


def test_every_demo_exists():
    from pathlib import Path
    demos = Path(appmod.__file__).parent / "templates" / "demos"
    for r in RELEASES:
        if r.demo:
            assert (demos / f"{r.demo}.html").is_file()


def test_sheet_never_on_the_login_page(gated_client):
    html = gated_client.get("/login").get_data(as_text=True)
    assert 'id="nv"' not in html


def test_preview_route_needs_the_env_switch(gated_client, monkeypatch):
    _login(gated_client)
    monkeypatch.delenv("NOVINKY_NAHLED", raising=False)
    assert gated_client.get("/novinky-nahled").status_code == 404
    monkeypatch.setenv("NOVINKY_NAHLED", "1")
    r = gated_client.get("/novinky-nahled?faze=2")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-start="sheet-still"' in html and "data-key" not in html


def test_dockerfile_copies_novinky_module():
    from pathlib import Path
    text = (Path(appmod.__file__).parent / "Dockerfile").read_text(encoding="utf-8")
    assert "novinky.py" in text
