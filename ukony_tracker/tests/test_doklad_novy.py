"""Nový doklad from evidence: the number and PDF come from žádosti (one numbering series)."""
from datetime import date, timedelta

import pytest
import requests

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import doklad_issue, ppd_links

TODAY = date.today().isoformat()
LONG_AGO = (date.today() - timedelta(days=200)).isoformat()


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
        other = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion")
        mk = lambda firma, **f: ukony_repo.create(conn, **{"firma_id": firma, "datum": TODAY,
                                                           "typ_kod": "NOVÉ", "celkem": 1300, **f})
        ids = {"a": mk(jene, rz="3BR9309"), "b": mk(jene, vin="TMBER6NW0V3099310"),
               "paid": mk(jene, rz="1AA1111", stav_platby="zaplaceno", zaplaceno_kc=1300),
               "old": mk(jene, rz="2AA2222", datum=LONG_AGO),
               "has_doklad": mk(jene, rz="3AA3333"), "other": mk(other, rz="4AA4444")}
        ppd_repo.upsert(conn, {"cislo": 170, "datum": TODAY, "castka": 1300,
                               "vozidlo": "3AA3333", "prijato_od": "X"})
    return {"jene": jene, "other": other, **ids}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def zadosti(monkeypatch):
    calls = []
    reply = {"response": None}

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if isinstance(reply["response"], Exception):
            raise reply["response"]
        return reply["response"]
    monkeypatch.setattr(doklad_issue.requests, "post", post)
    reply["response"] = FakeResponse(201, {"doklad": {
        "cislo": 183, "datum": "26.10.2026", "castka": 2600, "prijato_od": "JE & NE, SPOL. S R.O.",
        "prijato_ico": "44960263", "ucel": "ZASTUPOVÁNÍ NA MMB", "vozidlo": "3BR9309, TMBER6NW0V3099310",
        "zadost_id": "", "smazano": False}, "print_url": "/ppd-print/183"})
    return calls, reply


def _body(data, **over):
    return {"firma_id": data["jene"], "ukony": [data["a"], data["b"]], "prijato_od": "JE & NE, spol. s r.o.",
            "prijato_ico": "44960263", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB", "zpracoval": "David",
            **over}


def test_picker_lists_unpaid_recent_ukony_of_the_firm_without_a_doklad(client, data):
    body = client.get(f"/doklady/novy/ukony?firma={data['jene']}").get_json()
    assert [u["id"] for u in body["ukony"]] == sorted([data["a"], data["b"]], reverse=True)
    assert body["firma"] == {"nazev": "JE & NE, spol. s r.o.", "ico": "44960263"}
    assert body["ukony"][0]["vozidlo"] in ("3BR9309", "TMBER6NW0V3099310")


def test_issue_sends_the_contract_and_links_the_chosen_ukony(client, data, zadosti):
    calls, _ = zadosti
    response = client.post("/doklady/novy", json=_body(data))
    assert response.status_code == 201
    assert response.get_json() == {"cislo": 183, "print_url": "https://zadosti.spznaklic.cz/ppd-print/183"}
    call = calls[0]
    assert call["url"] == "http://zadosti-app:8089/api/ppd/vystavit"
    assert call["headers"] == {"X-Api-Key": "shared-key"}
    assert call["json"] == {"prijato_od": "JE & NE, spol. s r.o.", "prijato_ico": "44960263", "castka": 2600,
                            "ucel": "ZASTUPOVÁNÍ NA MMB", "vozidla": ["3BR9309", "TMBER6NW0V3099310"],
                            "zpracoval": "David"}
    with client.application.app_context():
        conn = db.get_db()
        assert ppd_repo.get_by_cislo(conn, 183)["castka"] == 2600
        assert ppd_links.compute(conn).by_doklad[183] == sorted([data["a"], data["b"]])
        # Payment stays a manual confirmation (orange button), never set by the doklad.
        assert ukony_repo.get(conn, data["a"])["stav_platby"] == "nezaplaceno"


@pytest.mark.parametrize("over,error", [
    ({"ukony": []}, "úkon"),
    ({"castka": 0}, "Částka"),
    ({"castka": "2600"}, "Částka"),
    ({"prijato_od": "  "}, "Přijato od"),
    ({"firma_id": 999}, "firm"),
])
def test_invalid_requests_never_reach_zadosti(client, data, zadosti, over, error):
    calls, _ = zadosti
    response = client.post("/doklady/novy", json=_body(data, **over))
    assert response.status_code == 400 and error.lower() in response.get_json()["error"].lower()
    assert calls == []


def test_ukony_of_another_firm_are_refused(client, data, zadosti):
    response = client.post("/doklady/novy", json=_body(data, ukony=[data["a"], data["other"]]))
    assert response.status_code == 400 and zadosti[0] == []


@pytest.mark.parametrize("reply,message", [
    (FakeResponse(404, {}), "není zapnuté"),
    (requests.ConnectionError("down"), "neodpovídají"),
    (FakeResponse(500, {}), "nepodařilo"),
    (FakeResponse(400, {"error": "Částka je moc velká."}), "Částka je moc velká."),
])
def test_zadosti_failure_saves_nothing(client, data, zadosti, reply, message):
    zadosti[1]["response"] = reply
    response = client.post("/doklady/novy", json=_body(data))
    assert response.status_code == 502 and message in response.get_json()["error"]
    with client.application.app_context():
        conn = db.get_db()
        assert ppd_repo.get_by_cislo(conn, 183) is None
        assert conn.execute("SELECT COUNT(*) FROM ppd_ukony").fetchone()[0] == 0


def test_not_configured_says_so_without_calling(client, data, zadosti, monkeypatch):
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "")
    response = client.post("/doklady/novy", json=_body(data))
    assert response.status_code == 502 and "není zapnuté" in response.get_json()["error"]
    assert zadosti[0] == []


def test_page_has_the_new_doklad_dialog(client, data):
    body = client.get("/doklady").get_data(as_text=True)
    assert 'data-doklad-novy' in body and 'id="doklad-modal"' in body
    assert f'<option value="{data["jene"]}">JE &amp; NE</option>' in body
