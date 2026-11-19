"""Stornované doklady (žádosti 1.36.0): evidence shows every doklad, a stornovaný
one greyed with "Stornováno · kdy · kdo", out of sums, unpaid counts, Zaplatit
and MONETA. 13. 11. 2026: faktura 0001 was hidden because /smazat answered
{"removed": false} and evidence took that as "already gone"."""
from datetime import date

import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import doklad_delete, moneta_job, ppd_links

TODAY = date.today().isoformat()
KEY = {"X-Api-Key": "shared-key"}


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


def _put(client, cislo, **fields):
    body = {"datum": TODAY, "castka": 1000, "prijato_od": "HOMELAND CZECH S.R.O.",
            "druh": "faktura", "splatnost": TODAY, **fields}
    return client.put(f"/api/ppd/{cislo}", json=body, headers=KEY)


def _row(client, cislo):
    with client.application.app_context():
        return ppd_repo.get_by_cislo(db.get_db(), cislo)


@pytest.fixture
def homeland(client):
    """0001 without a car (live), 0002 with a car linked to an úkon, both fakturas."""
    with client.application.app_context():
        conn = db.get_db()
        fid = firmy_repo.create(conn, nazev="HOMELAND CZECH s.r.o.", zkratka="Homeland", ico="12345678")
        uid = ukony_repo.create(conn, firma_id=fid, datum=TODAY, typ_kod="NOVÉ", celkem=1000,
                                vin="LRW3E7FS3VC007284")
    assert _put(client, 20260001, vozidlo="").status_code == 201
    assert _put(client, 20260002, vozidlo="LRW3E7FS3VC007284").status_code == 201
    return uid


# --- the push contract -----------------------------------------------------------

def test_storno_push_stores_when_and_who_and_obnovit_clears_them(client, homeland):
    r = _put(client, 20260001, smazano=True, storno_cas="2026-11-19T16:02:11", storno_kdo="David")
    assert r.status_code == 200
    row = _row(client, 20260001)
    assert (row["smazano"], row["storno_cas"], row["storno_kdo"]) == (1, "2026-11-19T16:02:11", "David")
    stamp = row["updated_at"]
    # The same state can arrive twice: nothing changes, not even the timestamp.
    _put(client, 20260001, smazano=True, storno_cas="2026-11-19T16:02:11", storno_kdo="David")
    assert _row(client, 20260001)["updated_at"] == stamp
    _put(client, 20260001, smazano=False, storno_cas="", storno_kdo="")
    row = _row(client, 20260001)
    assert (row["smazano"], row["storno_cas"], row["storno_kdo"]) == (0, None, None)


def test_a_push_without_storno_keys_keeps_the_stored_ones(client, homeland):
    _put(client, 20260001, smazano=True, storno_cas="2026-11-19T16:02:11", storno_kdo="David")
    _put(client, 20260001, smazano=True)  # an older žádosti build
    row = _row(client, 20260001)
    assert (row["storno_cas"], row["storno_kdo"]) == ("2026-11-19T16:02:11", "David")


@pytest.mark.parametrize("bad", [{"storno_cas": 5}, {"storno_kdo": ["x"]}, {"storno_cas": "včera"}])
def test_invalid_storno_fields_are_400(client, homeland, bad):
    assert _put(client, 20260001, smazano=True, **bad).status_code == 400


@pytest.mark.parametrize("empty", [{"zadost_id": ""}, {"zadost_id": None}, {}])
def test_an_empty_zadost_id_never_blanks_the_stored_one(client, homeland, empty):
    _put(client, 20260002, vozidlo="LRW3E7FS3VC007284", zadost_id="E75E6314-ABCD")
    _put(client, 20260002, vozidlo="LRW3E7FS3VC007284", **empty)
    assert _row(client, 20260002)["zadost_id"] == "E75E6314-ABCD"


# --- the page ---------------------------------------------------------------------

def _storno(client, cislo=20260001):
    _put(client, cislo, smazano=True, storno_cas="2026-11-19T16:02:11", storno_kdo="David")


def test_doklady_shows_a_stornovany_doklad_greyed_with_when_and_who(client, homeland):
    _storno(client)
    html = client.get("/doklady").get_data(as_text=True)
    item = html.split('data-cislo="20260001"')[1].split('class="doklad-item')[0]
    assert "is-smazany" in html.split('data-cislo="20260001"')[0][-200:]
    assert "Stornováno" in item and "19. 11. 16:02" in item and "David" in item
    assert "/doklady/20260001/smazat" not in item and "data-doklad-share" not in item


def test_stornovane_are_out_of_the_count_and_sum(client, homeland):
    _storno(client)
    html = client.get("/doklady").get_data(as_text=True)
    assert '<span id="doklady-count">1</span>' in html
    assert '<span id="doklady-sum">1 000</span>' in html
    assert 'data-cislo="20260001"' in html and 'data-cislo="20260002"' in html


@pytest.mark.parametrize("smazane, shown, hidden", [
    ("", ("20260001", "20260002"), ()),
    ("ne", ("20260002",), ("20260001",)),
    ("jen", ("20260001", "20260002"), ()),   # old "Stornované" link: section opened
    ("1", ("20260001", "20260002"), ()),   # old links: "I smazané"
])
def test_stornovane_filter(client, homeland, smazane, shown, hidden):
    _storno(client)
    html = client.get(f"/doklady?smazane={smazane}").get_data(as_text=True)
    for cislo in shown:
        assert f'data-cislo="{cislo}"' in html
    for cislo in hidden:
        assert f'data-cislo="{cislo}"' not in html


def test_a_stornovana_faktura_is_never_po_splatnosti_and_pays_nothing(client, homeland):
    _put(client, 20260002, vozidlo="LRW3E7FS3VC007284", splatnost="2026-01-01")
    _storno(client, 20260002)
    html = client.get("/doklady").get_data(as_text=True)
    item = html.split('data-cislo="20260002"')[1].split('class="doklad-item')[0]
    assert "po splatnosti" not in item and "Stornováno" in item
    with client.application.app_context():
        conn = db.get_db()
        assert ppd_links.compute(conn).by_ukon.get(homeland) is None  # no "Zaplatit · č. 0002"
        open_, paid = moneta_job._faktury(conn)
        assert 20260002 not in [r["cislo"] for r in open_] + paid


# --- the trash: no silent hide ------------------------------------------------------

class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def zadosti(monkeypatch):
    calls, reply = [], {"response": FakeResponse(200, {"removed": True})}

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return reply["response"]
    monkeypatch.setattr(doklad_delete.requests, "post", post)
    return calls, reply


def test_removed_false_keeps_the_doklad_live_and_says_so(client, homeland, zadosti):
    zadosti[1]["response"] = FakeResponse(200, {"removed": False})
    r = client.post("/doklady/20260001/smazat", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409 and r.get_json()["ok"] is False
    assert "nestornovaly" in r.get_json()["error"]
    assert _row(client, 20260001)["smazano"] == 0


def test_storno_from_evidence_sends_who_and_greys_the_doklad(client, homeland, zadosti):
    calls, _ = zadosti
    r = client.post("/doklady/20260001/smazat", data={"zpracoval": "David"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert calls[0]["json"] == {"kdo": "David"}
    row = _row(client, 20260001)
    assert row["smazano"] == 1 and row["storno_cas"] and row["storno_kdo"] == "David"
    assert "Stornováno" in client.get("/doklady").get_data(as_text=True)


def test_storno_without_a_profile_sends_no_body(client, homeland, zadosti):
    calls, _ = zadosti
    client.post("/doklady/20260001/smazat", headers={"X-Requested-With": "fetch"})
    assert "json" not in calls[0]


# --- 2.9.7: Zaplacené / Nezaplacené and the bank line ---------------------------------

def test_paid_filter_never_counts_stornovane(client, homeland):
    # 0001: faktura without a car, unpaid; 0002: its úkon unpaid; 0003: stornovaná.
    _put(client, 20260003, vozidlo="", smazano=True, storno_cas="2026-11-19T16:02:11")
    html = client.get("/doklady?stav=nezaplacene").get_data(as_text=True)
    assert 'data-cislo="20260001"' in html and 'data-cislo="20260002"' in html
    assert 'data-cislo="20260003"' not in html
    assert '<span id="doklady-count">2</span>' in html
    with client.application.app_context():
        conn = db.get_db()
        ukony_repo.update(conn, homeland, stav_platby="zaplaceno", zaplaceno_kc=1000)
    html = client.get("/doklady?stav=zaplacene").get_data(as_text=True)
    assert 'data-cislo="20260002"' in html
    assert 'data-cislo="20260001"' not in html and 'data-cislo="20260003"' not in html
    html = client.get("/doklady?stav=nezaplacene").get_data(as_text=True)
    assert 'data-cislo="20260001"' in html and 'data-cislo="20260002"' not in html


def test_a_faktura_paid_by_the_bank_without_ukony_counts_as_paid(client, homeland):
    with client.application.app_context():
        conn = db.get_db()
        conn.execute("UPDATE ppd SET zaplaceno_dne='2026-11-16' WHERE cislo=20260001")
        conn.commit()
    html = client.get("/doklady?stav=zaplacene").get_data(as_text=True)
    assert 'data-cislo="20260001"' in html


def test_the_filter_offers_three_states(client, homeland):
    # 2.9.8: Platné / Stornované are redundant now that stornované sit in their
    # own section; old links keep working.
    html = client.get("/doklady?stav=nezaplacene").get_data(as_text=True)
    for value, label in (("", "Všechny"), ("nezaplacene", "Nezaplacené"), ("zaplacene", "Zaplacené")):
        assert f'value="{value}"' in html and label in html
    assert 'value="nezaplacene" selected' in html
    assert 'value="platne"' not in html and 'value="storno"' not in html


def _main_list(html):
    return html.split('<div class="doklady-wrap">')[1].split('id="doklady-storno"')[0]


def test_stornovane_sit_in_a_closed_section_below_the_list(client, homeland):
    # David 19. 11.: out of the main list, collected at the bottom, closed.
    _storno(client)
    html = client.get("/doklady").get_data(as_text=True)
    assert 'data-cislo="20260001"' not in _main_list(html)
    assert 'data-cislo="20260002"' in _main_list(html)
    section = html.split('id="doklady-storno"')[1].split("</details>")[0]
    assert html.split('id="doklady-storno"')[0].rstrip().endswith('<details class="card recent-card doklady-storno"')
    assert section.startswith(">")  # no "open" attribute: closed by default
    assert 'Stornované (<span id="doklady-storno-n">1</span>)' in section
    assert 'data-cislo="20260001"' in section and "is-smazany" in section


def test_old_stornovane_link_opens_the_section(client, homeland):
    _storno(client)
    html = client.get("/doklady?stav=storno").get_data(as_text=True)
    assert 'id="doklady-storno" open' in html


def test_no_section_without_stornovane_or_in_platne(client, homeland):
    assert 'id="doklady-storno"' not in client.get("/doklady").get_data(as_text=True)
    _storno(client)
    assert 'id="doklady-storno"' not in client.get("/doklady?stav=platne").get_data(as_text=True)


def test_bank_check_sits_on_the_summary_line(client, homeland, monkeypatch):
    monkeypatch.setattr(moneta_job, "status_view", lambda conn: {"cas": "před 10 min", "pocet": 0,
                                                               "auth_failed": False})
    html = client.get("/doklady").get_data(as_text=True)
    summary = html.split('<span id="doklady-count">')[1].split("</div>")[0]
    assert '<span class="doklady-banka">Banka zkontrolována před 10 min</span>' in summary


def test_a_late_storno_reply_never_undoes_an_obnovit(client, homeland, monkeypatch):
    # astra 19. 11.: storno push, then obnovit push, then the original /smazat
    # reply {"removed": true} arrives — the doklad must stay live.
    def post(url, **kwargs):
        # The two pushes land while the trash request waits for žádosti.
        conn = db.connect(config.DB_PATH)
        base = {"cislo": 20260001, "datum": TODAY, "castka": 1000, "prijato_od": "HOMELAND CZECH S.R.O.",
                "druh": "faktura", "vozidlo": ""}
        ppd_repo.upsert(conn, {**base, "smazano": True, "storno_cas": "2026-11-19T19:40:00"})
        ppd_repo.upsert(conn, {**base, "smazano": False, "storno_cas": "", "storno_kdo": ""})
        conn.close()
        return FakeResponse(200, {"removed": True})
    monkeypatch.setattr(doklad_delete.requests, "post", post)
    client.post("/doklady/20260001/smazat", headers={"X-Requested-With": "fetch"})
    assert _row(client, 20260001)["smazano"] == 0


def test_a_stornovany_doklad_keeps_its_firm_in_the_firm_filter(client, homeland):
    # žádosti push the full record on storno (vozidlo included).
    _put(client, 20260002, vozidlo="LRW3E7FS3VC007284", smazano=True, storno_cas="2026-11-19T16:02:11")
    with client.application.app_context():
        conn = db.get_db()
        fid = conn.execute("SELECT firma_id FROM ukony WHERE id=?", (homeland,)).fetchone()[0]
        assert ppd_links.compute(conn).firma[20260002] == fid
    html = client.get(f"/doklady?firma={fid}").get_data(as_text=True)
    assert 'data-cislo="20260002"' in html and "Stornováno" in html
