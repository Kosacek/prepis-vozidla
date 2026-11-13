"""Faktura (platba převodem) in evidence: every new doklad is a faktura, druh
forwarded to žádosti, and a faktura never marking its úkony paid."""
from datetime import date, timedelta

import pytest
import requests

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import doklad_issue, doklad_moznosti, doklad_share, doklady_view, faktura_platby, ppd_links

TODAY = date.today()
RID = "6f1c2a1e-6b1d-4c55-9a3e-2f0a9d1b7c44"


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "shared-key")
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "http://zadosti-app:8089")
    monkeypatch.setattr(config, "ZADOSTI_PUBLIC_URL", "https://zadosti.example.cz")
    doklad_moznosti.reset_cache()
    ppd_links.invalidate()
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c
    doklad_moznosti.reset_cache()


@pytest.fixture
def data(client):
    with client.application.app_context():
        conn = db.get_db()
        firma = firmy_repo.create(conn, nazev="JE & NE, spol. s r.o.", zkratka="JE & NE", ico="44960263")
        mk = lambda **f: ukony_repo.create(conn, **{"firma_id": firma, "datum": TODAY.isoformat(),
                                                    "typ_kod": "NOVÉ", "celkem": 1300, **f})
        return {"firma": firma, "a": mk(rz="3BR9309"), "b": mk(rz="4BR1111")}


@pytest.fixture
def zadosti(monkeypatch):
    """Fake žádosti: moznosti (GET) and vystavit / sdilet (POST)."""
    state = {"gets": [], "posts": [], "moznosti": Resp(200, {"faktura": True, "splatnost_dni": 14}),
             "vystavit": None}

    def get(url, headers=None, timeout=None, allow_redirects=None):
        state["gets"].append({"url": url, "headers": headers})
        if isinstance(state["moznosti"], Exception):
            raise state["moznosti"]
        return state["moznosti"]

    def post(url, json=None, headers=None, timeout=None, allow_redirects=None):
        state["posts"].append({"url": url, "json": json, "headers": headers})
        return state["vystavit"]

    monkeypatch.setattr(doklad_moznosti.requests, "get", get)
    monkeypatch.setattr(doklad_issue.requests, "post", post)
    monkeypatch.setattr(doklad_share.requests, "post", post)
    return state


def _faktura_reply(cislo=20260001, splatnost=None):
    splatnost = splatnost or (TODAY + timedelta(days=14)).strftime("%d.%m.%Y")
    return Resp(201, {"doklad": {"druh": "faktura", "cislo": cislo, "datum": TODAY.strftime("%d.%m.%Y"),
                                 "splatnost": splatnost, "prijato_od": "JE & NE", "prijato_ico": "44960263",
                                 "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB", "vozidlo": "3BR9309, 4BR1111",
                                 "amount": 2600}})


def _ppd_reply(cislo=183):
    return Resp(201, {"doklad": {"cislo": cislo, "datum": TODAY.strftime("%d.%m.%Y"), "castka": 2600,
                                 "prijato_od": "JE & NE", "prijato_ico": "44960263", "vozidlo": "3BR9309"},
                      "print_url": f"/ppd-print/{cislo}"})


def _body(data, **over):
    return {"firma_id": data["firma"], "ukony": [data["a"], data["b"]], "prijato_od": "JE & NE",
            "prijato_ico": "44960263", "castka": 2600, "zpracoval": "David", "request_id": RID, **over}


# -- The modal: every new doklad is a faktura (2.9.1) -----------------------------

def _static(name):
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "static" / "js" / name).read_text(encoding="utf-8")


def _modal(client):
    """The Nový doklad modal only (the 2.9 release demo in the page still shows Hotově)."""
    html = client.get("/doklady").get_data(as_text=True)
    start = html.index('id="doklad-modal"')
    return html[start:html.index('id="dn-firmy-data"', start)]


def test_modal_is_a_faktura_and_never_offers_hotove(client, zadosti):
    html = _modal(client)
    assert "Nová faktura" in html and "Vystavit fakturu" in html
    assert 'data-faktura="1"' in html and "dn-unavailable" not in html
    assert 'id="dn-platba"' not in html and "Hotově" not in html and "Vystavit doklad" not in html
    assert zadosti["gets"][0]["url"] == "http://zadosti-app:8089/api/ppd/moznosti"
    assert zadosti["gets"][0]["headers"] == {"X-Api-Key": "shared-key"}


def test_modal_js_always_sends_druh_faktura_and_has_no_hotove_branch():
    js = _static("doklad_new.js")
    assert "payload.druh = 'faktura';" in js
    assert "if (prevodem)" not in js and "hotove" not in js and "Vystavit doklad" not in js
    assert "!fakturaOk ||" in js  # unavailable -> button stays disabled, submit is a no-op


def test_modal_placeholders_are_neutral_hints_without_helper_text(client, zadosti):
    html = _modal(client)
    assert 'placeholder="8 číslic"' in html and 'placeholder="SPZ nebo VIN"' in html
    assert 'placeholder="44960263"' not in html and "3BR9309, TMBER6NW0V3099310" not in html
    assert "Předvyplní se z úkonů" not in html


@pytest.mark.parametrize("answer", [
    Resp(200, {"faktura": False, "splatnost_dni": 14}),
    Resp(404, {"error": "x"}),
    Resp(500, {}),
    Resp(200, ValueError("not json")),
    Resp(200, {"faktura": "yes"}),
    requests.ConnectionError("down"),
])
def test_unavailable_faktura_disables_button_with_message_and_no_ppd_fallback(client, zadosti, answer):
    zadosti["moznosti"] = answer
    assert client.get("/doklady").status_code == 200
    html = _modal(client)
    assert 'data-faktura="0"' in html
    assert "Faktura teď nejde vystavit." in html and 'id="dn-unavailable"' in html
    assert "Vystavit fakturu" in html and "Vystavit doklad" not in html and 'id="dn-platba"' not in html


def test_moznosti_cached_for_about_five_minutes(client, zadosti, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(doklad_moznosti.time, "monotonic", lambda: now[0])
    client.get("/doklady"); client.get("/doklady")
    assert len(zadosti["gets"]) == 1
    now[0] += 299
    client.get("/doklady")
    assert len(zadosti["gets"]) == 1
    now[0] += 2
    client.get("/doklady")
    assert len(zadosti["gets"]) == 2


def test_failed_moznosti_is_retried_sooner_than_five_minutes(client, zadosti, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(doklad_moznosti.time, "monotonic", lambda: now[0])
    zadosti["moznosti"] = requests.ConnectionError("down")
    client.get("/doklady")
    zadosti["moznosti"] = Resp(200, {"faktura": True, "splatnost_dni": 14})
    now[0] += 31
    assert 'data-faktura="1"' in client.get("/doklady").get_data(as_text=True)


def test_no_zadosti_url_means_no_request(client, zadosti, monkeypatch):
    monkeypatch.setattr(config, "ZADOSTI_API_URL", "")
    html = client.get("/doklady").get_data(as_text=True)
    assert zadosti["gets"] == []


# -- Issuing -------------------------------------------------------------------

def test_druh_faktura_is_forwarded_and_stored_with_splatnost(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    res = client.post("/doklady/novy", json=_body(data, druh="faktura"))
    assert res.status_code == 201
    assert res.get_json() == {"cislo": 20260001, "druh": "faktura",
                              "print_url": "https://zadosti.example.cz/faktura-print/20260001"}
    assert zadosti["posts"][0]["json"]["druh"] == "faktura"
    with client.application.app_context():
        row = ppd_repo.get_by_cislo(db.get_db(), 20260001)
        assert row["druh"] == "faktura"
        assert row["splatnost"] == (TODAY + timedelta(days=14)).isoformat()


def test_ppd_request_stays_exactly_as_before(client, data, zadosti):
    zadosti["vystavit"] = _ppd_reply()
    assert client.post("/doklady/novy", json=_body(data)).status_code == 201
    assert "druh" not in zadosti["posts"][0]["json"]
    with client.application.app_context():
        row = ppd_repo.get_by_cislo(db.get_db(), 183)
        assert row["druh"] == "ppd" and row["splatnost"] is None


def test_faktura_nedostupna_gives_a_short_czech_409(client, data, zadosti):
    zadosti["vystavit"] = Resp(409, {"error": "faktura_nedostupna"})
    res = client.post("/doklady/novy", json=_body(data, druh="faktura"))
    assert res.status_code == 409
    assert "Faktura zatím není k dispozici" in res.get_json()["error"]
    with client.application.app_context():
        assert ppd_repo.list(db.get_db()) == []


def test_unknown_druh_is_rejected(client, data, zadosti):
    assert client.post("/doklady/novy", json=_body(data, druh="smlouva")).status_code == 400
    assert zadosti["posts"] == []


# -- Paid state: PPD vs faktura ---------------------------------------------------

def test_faktura_keeps_ukony_unpaid_until_the_payment_arrives(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    with client.application.app_context():
        conn = db.get_db()
        assert ppd_links.compute(conn).by_doklad[20260001] == sorted([data["a"], data["b"]])
        for k in ("a", "b"):
            u = ukony_repo.get(conn, data[k])
            assert u["stav_platby"] == "nezaplaceno" and u["zaplaceno_kc"] == 0


def test_ppd_still_leaves_ukony_for_manual_confirmation_and_faktura_is_the_same_until_paid(client, data, zadosti):
    # A PPD (cash) is confirmed by the orange button; a faktura only by the payment.
    zadosti["vystavit"] = _ppd_reply()
    client.post("/doklady/novy", json=_body(data, ukony=[data["a"]], castka=1300))
    with client.application.app_context():
        conn = db.get_db()
        assert ppd_links.compute(conn).by_doklad[183] == [data["a"]]
        assert ukony_repo.get(conn, data["a"])["stav_platby"] == "nezaplaceno"
        # ... and the PPD is never touched by the faktura settlement:
        assert faktura_platby.oznac_fakturu_zaplacenou(183, conn=conn) == 0
        assert ukony_repo.get(conn, data["a"])["stav_platby"] == "nezaplaceno"


def test_oznac_fakturu_zaplacenou_is_idempotent(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    with client.application.app_context():
        conn = db.get_db()
        assert faktura_platby.oznac_fakturu_zaplacenou(20260001, "2026-11-20", conn=conn) == 2
        for k in ("a", "b"):
            u = ukony_repo.get(conn, data[k])
            assert u["stav_platby"] == "zaplaceno" and u["zaplaceno_kc"] == 1300
        # a second call (the matcher fires twice) changes nothing, not even the date
        assert faktura_platby.oznac_fakturu_zaplacenou(20260001, "2026-11-25", conn=conn) == 0
        assert ppd_repo.get_by_cislo(conn, 20260001)["zaplaceno_dne"] == "2026-11-20"
        assert ukony_repo.get(conn, data["a"])["zaplaceno_kc"] == 1300


def test_oznac_fakturu_ignores_unknown_and_deleted(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    with client.application.app_context():
        conn = db.get_db()
        assert faktura_platby.oznac_fakturu_zaplacenou(99999999, conn=conn) == 0
        ppd_repo.mark_deleted(conn, 20260001)
        assert faktura_platby.oznac_fakturu_zaplacenou(20260001, conn=conn) == 0
        assert ukony_repo.get(conn, data["a"])["stav_platby"] == "nezaplaceno"


# -- The list ---------------------------------------------------------------------

def _row(client, cislo, dnes=None):
    with client.application.app_context():
        conn = db.get_db()
        links = ppd_links.compute(conn)
        rows = ppd_repo.list(conn, limit=None)
        ukony = ukony_repo.list_by_ids(conn, (u for r in rows for u in links.by_doklad.get(r["cislo"], [])))
        firmy = {f["id"]: f for f in firmy_repo.list_all(conn)}
        return next(r for r in doklady_view.radky(rows, links, ukony, firmy, {}, dnes) if r.cislo == cislo)


def test_list_rows_carry_druh_splatnost_and_the_unpaid_label(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply(splatnost="01.12.2026")
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    row = _row(client, 20260001, dnes=date(2026, 11, 20))
    assert (row.druh, row.splatnost, row.po_splatnosti) == ("faktura", "01.12.2026", False)
    assert (row.platba.stav, row.platba.label) == ("unpaid", "2 úkony")
    assert row.platba.title == "Faktura čeká na platbu · 2 úkony"
    assert "faktura" in row.hledat.split()


def test_past_due_and_unpaid_is_po_splatnosti_and_paid_turns_green(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply(splatnost="01.12.2026")
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    assert _row(client, 20260001, dnes=date(2026, 12, 2)).po_splatnosti is True
    assert _row(client, 20260001, dnes=date(2026, 12, 1)).po_splatnosti is False  # due day is not late
    with client.application.app_context():
        faktura_platby.oznac_fakturu_zaplacenou(20260001, "2026-12-02", conn=db.get_db())
    row = _row(client, 20260001, dnes=date(2026, 12, 5))
    assert row.platba.stav == "paid" and row.platba.label.startswith("✓") and row.po_splatnosti is False


def test_ppd_rows_are_unchanged(client, data, zadosti):
    with client.application.app_context():
        ppd_repo.upsert(db.get_db(), {"cislo": 190, "datum": TODAY.isoformat(), "castka": 1300,
                                      "vozidlo": "3BR9309", "prijato_od": "X"})
    row = _row(client, 190, dnes=date(2099, 1, 1))
    assert (row.druh, row.splatnost, row.po_splatnosti) == ("ppd", "", False)
    assert row.platba.label == "1 úkon"


def test_page_renders_faktura_tag_and_overdue_marker(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply(splatnost=(TODAY - timedelta(days=3)).strftime("%d.%m.%Y"))
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    html = client.get("/doklady").get_data(as_text=True)
    assert 'class="tag doklad-druh"' in html and "po splatnosti" in html and "čeká na platbu" in html
    assert 'class="doklady-list has-faktura"' in html
    assert 'data-druh="faktura"' in html


def test_page_without_faktura_has_no_faktura_markup(client, data, zadosti):
    with client.application.app_context():
        ppd_repo.upsert(db.get_db(), {"cislo": 190, "datum": TODAY.isoformat(), "castka": 1300, "vozidlo": "3BR9309"})
    html = client.get("/doklady").get_data(as_text=True)
    assert 'class="tag doklad-druh"' not in html and "po splatnosti" not in html
    assert 'class="doklady-list"' in html


# -- Share ------------------------------------------------------------------------

def test_share_of_a_faktura_sends_druh_and_print_goes_to_faktura_print(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    zadosti["vystavit"] = Resp(200, {"sdilet": "/4821", "plati_dni": 30})
    res = client.post("/doklady/20260001/sdilet")
    assert res.status_code == 200 and res.get_json()["kod"] == "4821"
    call = zadosti["posts"][-1]
    assert call["url"].endswith("/api/ppd/20260001/sdilet") and call["json"] == {"druh": "faktura"}
    assert doklad_share.tisk_base("faktura") == "https://zadosti.example.cz/faktura-print/"
    assert doklad_share.tisk_base() == "https://zadosti.example.cz/ppd-print/"
    html = client.get("/doklady").get_data(as_text=True)
    assert 'data-tisk-base-faktura="https://zadosti.example.cz/faktura-print/"' in html


def test_share_of_a_ppd_sends_no_body(client, data, zadosti):
    with client.application.app_context():
        ppd_repo.upsert(db.get_db(), {"cislo": 190, "datum": TODAY.isoformat(), "castka": 1300, "vozidlo": "3BR9309"})
    zadosti["vystavit"] = Resp(200, {"sdilet": "/4821", "plati_dni": 30})
    client.post("/doklady/190/sdilet")
    assert zadosti["posts"][-1]["json"] is None


# -- Storage ----------------------------------------------------------------------

def test_push_without_druh_does_not_reset_a_faktura(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply()
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    res = client.put("/api/ppd/20260001", json={"datum": TODAY.isoformat(), "castka": 2600},
                     headers={"X-Api-Key": "shared-key"})
    assert res.status_code in (200, 201)
    with client.application.app_context():
        assert ppd_repo.get_by_cislo(db.get_db(), 20260001)["druh"] == "faktura"


def test_migration_adds_columns_to_an_old_ppd_table(tmp_path):
    conn = db.connect(str(tmp_path / "old.db"))
    conn.executescript("CREATE TABLE ppd (id INTEGER PRIMARY KEY AUTOINCREMENT, cislo INTEGER UNIQUE NOT NULL,"
                       " datum TEXT NOT NULL, prijato_od TEXT, prijato_ico TEXT, castka INTEGER NOT NULL,"
                       " ucel TEXT, vozidlo TEXT, zadost_id TEXT, ukon_id INTEGER NULL,"
                       " smazano INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                       "INSERT INTO ppd(cislo, datum, castka, created_at, updated_at) VALUES(1,'2026-01-01',5,'x','x');")
    db.init_schema(conn)
    db.init_schema(conn)  # idempotent
    row = conn.execute("SELECT druh, splatnost, zaplaceno_dne FROM ppd").fetchone()
    assert tuple(row) == ("ppd", None, None)


# -- How a paid faktura was paid (2.9.3) --------------------------------------------

def _banka(client, cislo, datum="2026-11-13", stav="sparovano"):
    with client.application.app_context():
        conn = db.get_db()
        with conn:
            conn.execute(
                "INSERT INTO moneta_platby(tx_id, datum, castka, vs, faktura_cislo, stav, created_at)"
                " VALUES(?,?,?,?,?,?,?)", (f"tx{cislo}{stav}", datum, 1300.0, str(cislo), cislo, stav, "2026-11-13T10:00:00"))


def _row_banka(client, cislo):
    with client.application.app_context():
        conn = db.get_db()
        links = ppd_links.compute(conn)
        rows = ppd_repo.list(conn, limit=None)
        ukony = ukony_repo.list_by_ids(conn, (u for r in rows for u in links.by_doklad.get(r["cislo"], [])))
        firmy = {f["id"]: f for f in firmy_repo.list_all(conn)}
        return next(r for r in doklady_view.radky(rows, links, ukony, firmy, {}, banka=doklady_view.banka_platby(conn))
                    if r.cislo == cislo)


def _paid_faktura(client, data, zadosti):
    zadosti["vystavit"] = _faktura_reply(splatnost="01.12.2026")
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    with client.application.app_context():
        faktura_platby.oznac_fakturu_zaplacenou(20260001, "2026-11-13", conn=db.get_db())


def test_bank_matched_faktura_says_so(client, data, zadosti):
    _paid_faktura(client, data, zadosti)
    _banka(client, 20260001)
    p = _row_banka(client, 20260001).platba
    assert (p.stav, p.zpusob) == ("paid", "auto")
    assert p.title == "Zaplaceno převodem 13. 11. · spárováno automaticky"
    assert p.radek == "Zaplaceno převodem 13. 11. 2026 · automaticky"
    assert not p.label.startswith("✓")  # the bank icon replaces the tick
    html = client.get("/doklady").get_data(as_text=True)
    assert 'doklad-pocet__ico' in html and "has-ico" in html and "Zaplaceno převodem 13. 11. 2026 · automaticky" in html


def test_hand_marked_faktura_has_no_icon(client, data, zadosti):
    _paid_faktura(client, data, zadosti)
    _banka(client, 20260001, stav="nesparovano")  # an unmatched row proves nothing
    p = _row_banka(client, 20260001).platba
    assert (p.stav, p.zpusob, p.title, p.radek) == ("paid", "rucne", "Označeno ručně", "Označeno ručně")
    html = client.get("/doklady").get_data(as_text=True)
    assert 'doklad-pocet__ico' not in html and "Označeno ručně" in html


def test_cash_ppd_and_unpaid_faktura_are_unchanged(client, data, zadosti):
    with client.application.app_context():
        ppd_repo.upsert(db.get_db(), {"cislo": 190, "datum": TODAY.isoformat(), "castka": 1300,
                                      "vozidlo": "3BR9309", "prijato_od": "X"})
    p = _row_banka(client, 190).platba
    assert (p.zpusob, p.radek, p.title) == ("", "", "Čeká na zaplacení")
    zadosti["vystavit"] = _faktura_reply(splatnost="01.12.2026")
    client.post("/doklady/novy", json=_body(data, druh="faktura"))
    u = _row_banka(client, 20260001).platba
    assert (u.stav, u.zpusob, u.radek) == ("unpaid", "", "")


def test_bank_info_is_one_query_for_the_whole_list(client, data, zadosti):
    _paid_faktura(client, data, zadosti)
    _banka(client, 20260001)
    statements = []
    with client.application.app_context():
        conn = db.get_db()
        conn.set_trace_callback(statements.append)
        banka = doklady_view.banka_platby(conn)
        conn.set_trace_callback(None)
    assert banka == {20260001: "2026-11-13"}
    assert len([q for q in statements if "moneta_platby" in q]) == 1
