"""Koš na stránce Doklady maže doklad (přes žádosti), nikdy úkon.

27. 10. 2026: koš na řádku úkonu v rozbaleném dokladu č. 183 nevratně smazal
úkon 1533 — uživatel chtěl smazat doklad.
"""
import re
from datetime import date

import pytest
import requests

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import doklad_delete, ppd_links

TODAY = date.today().isoformat()
UKON_DELETE = re.compile(r"/ukony/\d+/smazat")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "shared-key")
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "http://zadosti-app:8089")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


@pytest.fixture
def data(client):
    with client.application.app_context():
        conn = db.get_db()
        jene = firmy_repo.create(conn, nazev="JE & NE, spol. s r.o.", zkratka="JE & NE", ico="44960263")
        mk = lambda **f: ukony_repo.create(conn, **{"firma_id": jene, "datum": TODAY,
                                                    "typ_kod": "NOVÉ", "celkem": 1300, **f})
        a, b = mk(rz="3BR9309"), mk(vin="TMBER6NW0V3099310")
        ppd_repo.upsert(conn, {"cislo": 183, "datum": TODAY, "castka": 2600,
                               "vozidlo": "3BR9309, TMBER6NW0V3099310", "prijato_od": "JE & NE"})
        ppd_links.set_explicit(conn, 183, [a, b])
    return {"a": a, "b": b}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


@pytest.fixture
def zadosti(monkeypatch):
    calls = []
    reply = {"response": FakeResponse(200, {"removed": True})}

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(reply["response"], Exception):
            raise reply["response"]
        return reply["response"]
    monkeypatch.setattr(doklad_delete.requests, "post", post)
    return calls, reply


def _snapshot(client):
    """Every úkon and every doklad↔úkon link, column by column."""
    with client.application.app_context():
        conn = db.get_db()
        return ([tuple(r) for r in conn.execute("SELECT * FROM ukony ORDER BY id")],
                [tuple(r) for r in conn.execute("SELECT * FROM ppd_ukony ORDER BY ppd_cislo, ukon_id")])


def _smazano(client, cislo=183):
    with client.application.app_context():
        return ppd_repo.get_by_cislo(db.get_db(), cislo)["smazano"]


def _delete(client, cislo=183, **kw):
    return client.post(f"/doklady/{cislo}/smazat", headers={"X-Requested-With": "fetch"}, **kw)


# --- the page -------------------------------------------------------------

def test_doklady_page_trash_deletes_the_doklad_never_the_ukon(client, data):
    html = client.get("/doklady").get_data(as_text=True)
    assert html.count('action="/doklady/183/smazat"') == 2  # one per úkon row, same layout
    assert "Smazat doklad č. 183?" in html
    assert not UKON_DELETE.search(html)


def test_without_zadosti_the_doklad_trash_is_disabled(client, data, monkeypatch):
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "")
    html = client.get("/doklady").get_data(as_text=True)
    assert re.search(r'<button[^>]*class="row-del"[^>]*\bdisabled\b', html)
    assert not UKON_DELETE.search(html)


def test_an_already_deleted_doklad_shows_no_trash(client, data):
    # A deleted doklad pays nothing, so its drawer lists no úkony to trash.
    with client.application.app_context():
        ppd_repo.mark_deleted(db.get_db(), 183)
    html = client.get("/doklady?smazane=1").get_data(as_text=True)
    assert 'data-cislo="183"' in html
    assert "/doklady/183/smazat" not in html
    assert not UKON_DELETE.search(html)


@pytest.mark.parametrize("vozidlo", ["AAAAAAAAAA", ""])
def test_a_doklad_without_ukony_still_has_its_trash(client, data, vozidlo):
    # 12. 11. 2026: doklad č. 219 (vozidlo "AAAAAAAAAA", issued by mistake)
    # matched no úkon, so its drawer had no úkon row to carry the trash and
    # David could not delete it.
    with client.application.app_context():
        ppd_repo.upsert(db.get_db(), {"cislo": 219, "datum": TODAY, "castka": 1300,
                                      "vozidlo": vozidlo, "prijato_od": "AAAAAA"})
    html = client.get("/doklady").get_data(as_text=True)
    assert html.count('action="/doklady/219/smazat"') == 1
    assert "Smazat doklad č. 219?" in html
    assert html.count('action="/doklady/183/smazat"') == 2  # linked doklady unchanged
    assert not UKON_DELETE.search(html)


def test_ukony_page_trash_still_deletes_ukony(client, data):
    html = client.get("/ukony/vse").get_data(as_text=True)
    assert f'action="/ukony/{data["a"]}/smazat"' in html
    assert "/doklady/183/smazat" not in html


# --- deleting a doklad ------------------------------------------------------

def test_delete_asks_zadosti_and_hides_the_doklad_keeping_its_ukony(client, data, zadosti):
    calls, _ = zadosti
    before = _snapshot(client)
    r = _delete(client)
    assert r.status_code == 200 and r.get_json() == {"ok": True, "cislo": 183}
    assert [c["url"] for c in calls] == ["http://zadosti-app:8089/api/ppd/183/smazat"]
    assert calls[0]["headers"] == {"X-Api-Key": "shared-key"}
    assert calls[0]["allow_redirects"] is False  # the login page is not a success
    assert _smazano(client) == 1
    assert _snapshot(client) == before
    assert 'data-cislo="183"' not in client.get("/doklady").get_data(as_text=True)


def test_zadosti_no_longer_having_the_doklad_still_hides_it(client, data, zadosti):
    zadosti[1]["response"] = FakeResponse(200, {"removed": False})
    before = _snapshot(client)
    assert _delete(client).status_code == 200
    assert _smazano(client) == 1
    assert _snapshot(client) == before


@pytest.mark.parametrize("response", [
    FakeResponse(401, {"error": "Neplatný klíč."}),
    FakeResponse(503, {"error": "Vypnuto."}),
    FakeResponse(500, {}),
    FakeResponse(404, None),                 # endpoint not there yet
    FakeResponse(302, None),                 # login redirect
    FakeResponse(200, None),                 # HTML, not JSON
    FakeResponse(200, {"success": True}),    # no "removed"
    FakeResponse(200, {"removed": "yes"}),
    requests.ConnectionError("down"),
    requests.Timeout("slow"),
])
def test_any_failure_changes_nothing(client, data, zadosti, response):
    zadosti[1]["response"] = response
    before = _snapshot(client)
    r = _delete(client)
    body = r.get_json()
    assert r.status_code == 502 and body["ok"] is False and body["error"]
    assert _smazano(client) == 0
    assert _snapshot(client) == before


def test_without_zadosti_nothing_is_sent(client, data, zadosti, monkeypatch):
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "")
    r = _delete(client)
    assert r.status_code == 503 and r.get_json()["ok"] is False
    assert zadosti[0] == [] and _smazano(client) == 0


def test_unknown_doklad_is_404_without_a_call(client, data, zadosti):
    r = _delete(client, cislo=999)
    assert r.status_code == 404 and r.get_json()["ok"] is False
    assert zadosti[0] == []


def test_already_deleted_doklad_is_not_sent_again(client, data, zadosti):
    with client.application.app_context():
        ppd_repo.mark_deleted(db.get_db(), 183)
    r = _delete(client)
    assert r.status_code == 409 and r.get_json()["ok"] is False
    assert zadosti[0] == []


def test_plain_form_post_redirects_back_with_a_message(client, data, zadosti):
    r = client.post("/doklady/183/smazat", data={"back": "/doklady?q=3br"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/doklady?q=3br")
    assert "Doklad č. 183 smazán." in client.get("/doklady").get_data(as_text=True)


def test_plain_form_post_failure_flashes_the_error(client, data, zadosti):
    zadosti[1]["response"] = FakeResponse(503, {"error": "Vypnuto."})
    r = client.post("/doklady/183/smazat", data={"back": "https://evil.example/"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/doklady")
    assert _smazano(client) == 0
    assert "nepodařilo smazat" in client.get("/doklady").get_data(as_text=True)


# --- the úkon delete refuses anything coming from Doklady -------------------

@pytest.mark.parametrize("back, referer", [
    ("/doklady?mesic=2026-10", None),   # a Doklady tab still open from before the fix
    ("", "http://localhost/doklady"),
])
def test_ukon_delete_from_doklady_is_refused(client, data, back, referer):
    headers = {"X-Requested-With": "fetch", **({"Referer": referer} if referer else {})}
    before = _snapshot(client)
    r = client.post(f"/ukony/{data['a']}/smazat", data={"back": back}, headers=headers)
    assert r.status_code == 409 and r.get_json()["ok"] is False
    assert _snapshot(client) == before


def test_ukon_delete_from_doklady_plain_post_flashes_and_keeps_it(client, data):
    before = _snapshot(client)
    r = client.post(f"/ukony/{data['a']}/smazat", data={"back": "/doklady"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/doklady")
    assert _snapshot(client) == before
    assert "maže jen doklad" in client.get("/doklady").get_data(as_text=True)


def test_ukon_delete_from_ukony_page_still_works(client, data):
    r = client.post(f"/ukony/{data['a']}/smazat", data={"back": "/ukony/vse"},
                    headers={"X-Requested-With": "fetch", "Referer": "http://localhost/ukony/vse"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    with client.application.app_context():
        assert ukony_repo.get(db.get_db(), data["a"]) is None
