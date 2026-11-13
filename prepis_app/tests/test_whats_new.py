"""„Co je nového“ (card + sheet „Co umí Žádosti“) + the „Nová verze“ bar."""
from app import __version__
import novinky
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


def test_bottom_bar_version_opens_the_sheet(client):
    html = client.get("/").get_data(as_text=True)
    assert f"v{__version__}" in html and "data-releases-open" in html
    # The old version browser is gone; the new card + sheet are in.
    assert "Starší" not in html and "Novější" not in html
    assert "Co umí Žádosti" in html
    assert f'data-key="zadosti_whatsnew_{CURRENT_RELEASE}"' in html
    assert 'data-start="auto"' in html


def test_superseded_and_obsolete_releases_never_appear(client):
    html = client.get("/").get_data(as_text=True)
    shown = {k["version"] for s in novinky.sekce(CURRENT_RELEASE) for k in s["karty"]}
    nahrazene = {v for r in RELEASES for v in r.nahrazuje}
    hidden = nahrazene | {r.version for r in RELEASES if r.zastarale}
    assert hidden and not (hidden & shown)
    for v in hidden:
        assert f'data-version="{v}"' not in html


def test_newest_release_is_the_one_popped(client):
    html = client.get("/").get_data(as_text=True)
    assert RELEASES[0].version == CURRENT_RELEASE == __version__
    card = html[html.index('class="nv-intro"'):]
    assert f"Verze {CURRENT_RELEASE}" in card.split("nv-timer")[0]
    assert RELEASES[0].title in card.split("nv-timer")[0]


def test_sheet_lists_every_current_release_exactly_once(client):
    html = client.get("/").get_data(as_text=True)
    current = [r.version for r in novinky.aktualni()]
    assert current and current[0] == CURRENT_RELEASE
    for v in current:
        assert html.count(f'data-version="{v}"') == 1
    assert html.count('class="nv-fe') == len(current)
    # The two un-hidden ones are back, worded for fakturas.
    assert "1.10.0" in current and "1.3.0" in current
    assert "pokladní doklad" not in "".join(
        r.radek or "" for r in RELEASES if r.version in ("1.10.0", "1.3.0"))


def test_every_release_has_a_classification():
    for r in RELEASES:
        assert r.oblast or r.zastarale or r.version in {v for x in RELEASES for v in x.nahrazuje}, r.version
        if r.oblast:
            assert r.oblast in dict(novinky.SEKCE)


def test_preview_route_only_behind_env_flag(client, monkeypatch):
    monkeypatch.delenv("NOVINKY_NAHLED", raising=False)
    assert client.get("/novinky-nahled").status_code == 404
    monkeypatch.setenv("NOVINKY_NAHLED", "1")
    assert client.get("/novinky-nahled").status_code == 200


def test_build_endpoint_and_page_stamp_agree(client):
    r = client.get("/verze")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    build = r.get_json()["build"]
    assert isinstance(build, str) and len(build) >= 8
    html = client.get("/").get_data(as_text=True)
    assert f'var pageBuild = "{build}";' in html
    assert "Nová verze aplikace" in html
