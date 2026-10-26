"""Orange "Zaplatit": an unpaid úkon that a doklad pays asks only for confirmation (David 2026-10-26)."""
import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


@pytest.fixture
def ids(client):
    with client.application.app_context():
        conn = db.get_db()
        fid = firmy_repo.create(conn, nazev="JE & NE, spol. s r.o.", zkratka="JE & NE")
        mk = lambda **f: ukony_repo.create(conn, **{"firma_id": fid, "datum": "2026-10-26",
                                                     "typ_kod": "NOVÉ", "celkem": 1300, **f})
        ids = {"s_dokladem": mk(rz="3BR9309"), "bez_dokladu": mk(rz="3BR7164"),
               "zaplaceny": mk(rz="5AB1234", stav_platby="zaplaceno", zaplaceno_kc=1300)}
        ppd_repo.upsert(conn, {"cislo": 183, "datum": "2026-10-26", "castka": 2600,
                               "prijato_od": "JE & NE", "vozidlo": "3BR9309, 5AB1234"})
    return ids


def _item(body, uid):
    return body.split(f'/ukony/{uid}/upravit')[1].split('class="ukony-item"')[0]


def test_unpaid_ukon_with_a_doklad_gets_the_orange_button(client, ids):
    body = client.get("/ukony/vse").get_data(as_text=True)
    orange = _item(body, ids["s_dokladem"])
    assert "pay-doklad" in orange
    assert 'title="Doklad č. 183 — potvrď platbu"' in orange
    assert "Zaplatit · doklad č. 183" in orange


def test_no_doklad_or_already_paid_stays_as_before(client, ids):
    body = client.get("/ukony/vse").get_data(as_text=True)
    assert "pay-doklad" not in _item(body, ids["bez_dokladu"])
    assert "pay-doklad" not in _item(body, ids["zaplaceny"])


def test_cancelling_a_payment_brings_the_orange_button_back(client, ids):
    uid = ids["zaplaceny"]
    response = client.post(f"/ukony/{uid}/zaplaceno", data={"castka": "0", "back": "/ukony/vse"},
                           headers={"X-Requested-With": "fetch"})
    html = response.get_json()["stav_slot_html"]
    assert "pay-doklad" in html and "č. 183" in html


def test_orange_button_inside_the_doklad_drawer(client, ids):
    body = client.get("/doklady").get_data(as_text=True)
    drawer = body.split('id="doklad-183"')[1]
    assert "pay-doklad" in drawer
