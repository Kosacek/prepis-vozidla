"""Doklady 2.8 (David, 12. 11. 2026): a row shows the firm at a glance, the
car's SPZ + VIN, whether its úkony are paid, and one share icon (Tisk /
Sdílet kódem)."""
from datetime import date

import pytest
import requests

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import doklad_share, doklady_view, ppd_links

TODAY = date.today().isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "shared-key")
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "http://zadosti-app:8089")
    monkeypatch.setattr(config, "ZADOSTI_PUBLIC_URL", "https://zadosti.example.cz")
    ppd_links.invalidate()
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
                                                    "typ_kod": "PŘEVOD", "celkem": 1300, **f})
        paid = mk(rz="1BM1760", vin="TMBJJ7NE5J0123456", stav_platby="zaplaceno", zaplaceno_kc=1300)
        unpaid = mk(rz="3BR9309", vin="TMBER6NW0V3099310")
        part_a = mk(rz="5AA5555", stav_platby="zaplaceno", zaplaceno_kc=1300)
        part_b = mk(rz="6AA6666")
        one_part = mk(rz="7AA7777", stav_platby="castecne", zaplaceno_kc=300)
        for cislo, vozidlo in ((201, "1BM1760"), (202, "TMBER6NW0V3099310"), (203, "5AA5555, 6AA6666"),
                               (204, "7AA7777"), (205, "9ZZ9999")):
            ppd_repo.upsert(conn, {"cislo": cislo, "datum": TODAY, "castka": 1300,
                                   "vozidlo": vozidlo, "prijato_od": "PTÁČEK - VELKOOBCHOD, A.S."})
        ppd_repo.upsert(conn, {"cislo": 206, "datum": TODAY, "castka": 1300, "vozidlo": "",
                               "prijato_od": "SMAZANÝ", "smazano": True})
        ppd_links.invalidate()
    return {"jene": jene, "paid": paid, "unpaid": unpaid, "part_a": part_a, "part_b": part_b,
            "one_part": one_part}


def _rows(client):
    with client.application.test_request_context():
        conn = db.get_db()
        links = ppd_links.compute(conn)
        rows = ppd_repo.list(conn, include_deleted=True, limit=None)
        ukony = ukony_repo.list_by_ids(conn, (u for r in rows for u in links.by_doklad.get(r["cislo"], [])))
        firmy = {f["id"]: f for f in firmy_repo.list_all(conn)}
        return {r.cislo: r for r in doklady_view.radky(rows, links, ukony, firmy, {"JE & NE": "#34c759"})}


# -- Row model -----------------------------------------------------------------

def test_row_shows_spz_and_vin_of_the_linked_ukon(client, data):
    row = _rows(client)[201]
    assert [(a.spz, a.vin) for a in row.auta] == [("1BM1760", "TMBJJ7NE5J0123456")]


def test_vin_only_doklad_still_shows_the_spz_of_its_ukon(client, data):
    row = _rows(client)[202]
    assert [(a.spz, a.vin) for a in row.auta] == [("3BR9309", "TMBER6NW0V3099310")]


def test_car_without_ukon_is_kept_and_marked_missing(client, data):
    row = _rows(client)[205]
    assert [(a.spz, a.vin, a.chybi) for a in row.auta] == [("9ZZ9999", "", True)]


def test_row_carries_the_firm_and_its_colour(client, data):
    assert _rows(client)[201].firma == {"zkratka": "JE & NE", "color": "#34c759"}


@pytest.mark.parametrize("cislo,stav,label", [
    (201, "paid", "✓ 1 úkon"),
    (202, "unpaid", "1 úkon"),
    (203, "partial", "◐ 1/2 zapl."),
    (204, "partial", "◐ částečně"),
    (205, "none", "bez úkonu"),
])
def test_ukon_chip_says_whether_its_ukony_are_paid(client, data, cislo, stav, label):
    platba = _rows(client)[cislo].platba
    assert (platba.stav, platba.label) == (stav, label)


def test_variable_symbol_is_the_doklad_number(client, data):
    # Moneta QR payments (next project) pair a payment to the doklad by VS.
    assert _rows(client)[203].vs == "203"


def test_search_text_covers_firm_spz_and_vin(client, data):
    hledat = _rows(client)[201].hledat
    for part in ("201", "je & ne", "1bm1760", "tmbjj7ne5j0123456", "ptáček"):
        assert part in hledat


# -- Page ----------------------------------------------------------------------

def test_list_shows_the_vin_and_a_coloured_firm_chip(client, data):
    html = client.get("/doklady").get_data(as_text=True)
    assert "TMBJJ7NE5J0123456" in html
    assert 'class="doklad-firma-chip"' in html and "--firma: #" in html


def test_every_valid_doklad_has_one_share_icon(client, data):
    html = client.get("/doklady?smazane=1").get_data(as_text=True)
    for cislo in (201, 202, 203, 204, 205):
        assert html.count(f'data-doklad-share="{cislo}"') == 1
    assert 'data-doklad-share="206"' not in html


def test_share_sheet_offers_print_and_share_code(client, data):
    html = client.get("/doklady").get_data(as_text=True)
    assert 'id="doklad-share"' in html
    assert "data-share-tisk" in html and "data-share-kod" in html
    assert 'data-tisk-base="https://zadosti.example.cz/ppd-print/"' in html


def test_paid_chip_is_green_in_the_list(client, data):
    html = client.get("/doklady").get_data(as_text=True)
    assert 'doklad-pocet is-paid' in html and 'doklad-pocet is-unpaid' in html


def test_firm_filter_options_carry_their_colour(client, data):
    html = client.get("/doklady").get_data(as_text=True)
    assert f'<option value="{data["jene"]}" data-color="#' in html


# -- Sdílet kódem (proxy to žádosti POST /api/ppd/<n>/sdilet) -------------------

class FakeResponse:
    def __init__(self, status, body=None, text=False):
        self.status_code, self._body, self._text = status, body, text

    def json(self):
        if self._text:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def zadosti(monkeypatch):
    calls, reply = [], {"response": FakeResponse(200, {"sdilet": "/4821", "plati_dni": 30})}

    def post(url, headers=None, timeout=None, allow_redirects=True, **kw):
        calls.append({"url": url, "headers": headers, "allow_redirects": allow_redirects})
        if isinstance(reply["response"], Exception):
            raise reply["response"]
        return reply["response"]
    monkeypatch.setattr(doklad_share.requests, "post", post)
    return calls, reply


def test_share_code_comes_from_zadosti_with_the_integration_key(client, data, zadosti):
    calls, _ = zadosti
    res = client.post("/doklady/201/sdilet")
    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "kod": "4821", "url": "https://zadosti.example.cz/4821",
                              "plati_dni": 30}
    assert calls[0]["url"] == "http://zadosti-app:8089/api/ppd/201/sdilet"
    assert calls[0]["headers"] == {"X-Api-Key": "shared-key"}
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("response,status,error", [
    (FakeResponse(404, text=True), 501, "Sdílení kódem žádosti zatím neumí."),
    (FakeResponse(302, text=True), 501, "Sdílení kódem žádosti zatím neumí."),
    (FakeResponse(404, {"error": "Doklad nenalezen."}), 404, "Doklad nenalezen."),
    (FakeResponse(200, {"sdilet": "javascript:alert(1)"}), 502, "Kód se nepodařilo vytvořit."),
    (FakeResponse(500, text=True), 502, "Kód se nepodařilo vytvořit."),
    (requests.ConnectionError("down"), 502, "Žádosti neodpovídají, kód se nevytvořil. Zkus to za chvíli."),
])
def test_share_failures_say_what_happened(client, data, zadosti, response, status, error):
    zadosti[1]["response"] = response
    res = client.post("/doklady/201/sdilet")
    assert res.status_code == status
    assert res.get_json() == {"ok": False, "error": error}


@pytest.mark.parametrize("cislo,status", [(206, 409), (999, 404)])
def test_deleted_or_unknown_doklad_never_reaches_zadosti(client, data, zadosti, cislo, status):
    assert client.post(f"/doklady/{cislo}/sdilet").status_code == status
    assert zadosti[0] == []


def test_share_not_configured_says_so(client, data, zadosti, monkeypatch):
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "")
    res = client.post("/doklady/201/sdilet")
    assert res.status_code == 503 and zadosti[0] == []


def test_share_code_takes_no_backup(client, data, zadosti, monkeypatch):
    # Like a "Zeptej se" question it writes nothing; a backup per tap would
    # push real ones out of the 30-backup rotation.
    calls = []
    monkeypatch.setattr(db, "backup_db", lambda *a, **k: calls.append(1))
    assert client.post("/doklady/201/sdilet").status_code == 200
    assert calls == []
