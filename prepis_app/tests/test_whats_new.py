"""Version history ("v1.21.0 ⓘ" in the bottom bar) + the "Nová verze" bar."""
from app import __version__
from releases import CURRENT_RELEASE, RELEASES


def _v(s):
    return tuple(int(x) for x in s.split("."))


def test_releases_are_newest_first_and_well_formed():
    versions = [r.version for r in RELEASES]
    assert len(set(versions)) == len(versions)
    assert [_v(v) for v in versions] == sorted((_v(v) for v in versions), reverse=True)
    dates = [r.date for r in RELEASES]
    assert dates == sorted(dates, reverse=True)
    for r in RELEASES:
        assert r.title and 1 <= len(r.points) <= 2
    # History can't announce a version the app isn't running yet.
    assert _v(CURRENT_RELEASE) <= _v(__version__)


def test_bottom_bar_version_opens_the_whole_history(client):
    html = client.get("/").get_data(as_text=True)
    assert f"v{__version__}" in html and "data-releases-open" in html
    for r in RELEASES:
        assert r.title in html
    assert "Starší" in html and "Novější" in html
    assert f"zadosti_whatsnew_{CURRENT_RELEASE}" in html


def test_build_endpoint_and_page_stamp_agree(client):
    r = client.get("/verze")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    build = r.get_json()["build"]
    assert isinstance(build, str) and len(build) >= 8
    html = client.get("/").get_data(as_text=True)
    assert f'var pageBuild = "{build}";' in html
    assert "Nová verze aplikace" in html
