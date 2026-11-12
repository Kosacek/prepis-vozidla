"""MONETA payment matching: parsing, matcher, job, scheduling, UI. Fake clients only."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import moneta_client as mc
from services import moneta_job, moneta_matcher, ppd_links

TODAY = date.today().isoformat()


def P(id="t1", castka=1300, vs="", zprava="", datum=TODAY, protiucet="123/0600"):
    return mc.Platba(id, datum, Decimal(castka), "CZK", vs, zprava, protiucet)


def F(cislo, castka=1300, vozidlo=""):
    return {"cislo": cislo, "castka": castka, "vozidlo": vozidlo}


# ---------------------------------------------------------------- parsing

def test_parse_cobs_credit():
    raw = {"entryReference": "E1", "amount": {"value": "1300.00", "currency": "CZK"},
           "creditDebitIndicator": "CRDT", "bookingDate": "2026-11-10",
           "remittanceInformation": {"unstructured": "faktura", "structured": {"variableSymbol": "0020260001"}},
           "debtorAccount": {"iban": "CZ650800000000001234"}}
    p = mc._parse_transaction(raw)
    assert (p.id, p.datum, p.castka, p.vs, p.zprava) == ("E1", "2026-11-10", Decimal("1300.00"), "20260001", "faktura")
    assert "CZ65" in p.protiucet


def test_parse_berlin_style_and_flat():
    p = mc._parse_transaction({"transactionId": "B1", "transactionAmount": {"amount": "500", "currency": "CZK"},
                               "bookingDate": "2026-11-10T08:00:00Z", "variableSymbol": "7",
                               "remittanceInformationUnstructured": "VIN"})
    assert p.id == "B1" and p.vs == "7" and p.castka == 500
    q = mc._parse_transaction({"id": 9, "amount": "10,5", "currency": "CZK", "valueDate": "2026-11-01"})
    assert q.castka == Decimal("10.5") and q.id == "9"


def test_parse_ignores_debit_foreign_and_garbage():
    base = {"entryReference": "x", "bookingDate": "2026-11-10"}
    assert mc._parse_transaction({**base, "amount": {"value": "5", "currency": "CZK"},
                                  "creditDebitIndicator": "DBIT"}) is None
    assert mc._parse_transaction({**base, "amount": {"value": "5", "currency": "EUR"},
                                  "creditDebitIndicator": "CRDT"}) is None
    assert mc._parse_transaction({**base, "transactionAmount": {"amount": "-5", "currency": "CZK"}}) is None
    assert mc._parse_transaction({**base, "amount": {"value": "abc", "currency": "CZK"}}) is None
    assert mc._parse_transaction("nope") is None


def test_parse_without_id_gets_stable_fingerprint():
    raw = {"amount": {"value": "5", "currency": "CZK"}, "creditDebitIndicator": "CRDT", "bookingDate": "2026-11-10"}
    assert mc._parse_transaction(raw).id == mc._parse_transaction(dict(raw)).id


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, *resps):
        self.resps, self.calls = list(resps), []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resps.pop(0)


def _tx(i):
    return {"entryReference": f"T{i}", "amount": {"value": "1", "currency": "CZK"},
            "creditDebitIndicator": "CRDT", "bookingDate": "2026-11-10"}


def test_client_follows_next_link_and_sends_bearer():
    s = FakeSession(FakeResp(200, {"transactions": [_tx(1)], "_links": {"next": {"href": "/p2"}}}),
                    FakeResp(200, {"transactions": [_tx(2)]}))
    out = mc.MonetaClient(token="tok", account_id="A", session=s).fetch_incoming("2026-11-01")
    assert [p.id for p in out] == ["T1", "T2"]
    assert s.calls[1][0].endswith("/p2")
    assert s.calls[0][1]["headers"]["Authorization"] == "Bearer tok"
    assert s.calls[0][1]["timeout"]


def test_client_page_cap_and_errors():
    loop = [FakeResp(200, {"transactions": [_tx(1)], "pageNumber": i, "pageCount": 999}) for i in range(50)]
    s = FakeSession(*loop)
    mc.MonetaClient(token="t", account_id="A", session=s).fetch_incoming("2026-11-01")
    assert len(s.calls) == mc.MAX_PAGES
    with pytest.raises(mc.MonetaAuthError):
        mc.MonetaClient(token="t", account_id="A", session=FakeSession(FakeResp(401, {}))).fetch_incoming("2026-11-01")
    with pytest.raises(mc.MonetaError):
        mc.MonetaClient(token="t", account_id="A", session=FakeSession(FakeResp(500, {}))).fetch_incoming("2026-11-01")


# ---------------------------------------------------------------- matcher

def test_vs_hit():
    shody, nes = moneta_matcher.sparuj([P(vs="20260001")], [F(20260001)])
    assert shody == [(P(vs="20260001"), 20260001)] and nes == []


def test_vin_and_plate_fallback():
    vin = "WVWZZZ1KZAW123456"
    s, _ = moneta_matcher.sparuj([P(zprava=f"za auto {vin.lower()}")], [F(1, vozidlo=vin), F(2, vozidlo="3BR9309")])
    assert s[0][1] == 1
    s, _ = moneta_matcher.sparuj([P(zprava="rz 3br 9309")], [F(1, vozidlo=vin), F(2, vozidlo="3BR9309")])
    assert s[0][1] == 2


def test_amount_mismatch_never_settles():
    s, n = moneta_matcher.sparuj([P(castka=1200, vs="5")], [F(5, 1300)])
    assert s == [] and n[0][1] == "částka nesedí (přišlo 1 200, faktura 1 300)"
    s, n = moneta_matcher.sparuj([P(castka=1200, zprava="3BR9309")], [F(5, 1300, "3BR9309")])
    assert s == [] and "částka nesedí" in n[0][1]


def test_two_candidates_and_no_match():
    s, n = moneta_matcher.sparuj([P(zprava="3BR9309")], [F(1, vozidlo="3BR9309"), F(2, vozidlo="3BR9309")])
    assert s == [] and "více možných" in n[0][1]
    s, n = moneta_matcher.sparuj([P(zprava="nic")], [F(1, vozidlo="3BR9309")])
    assert s == [] and n[0][1] == "žádná odpovídající faktura"


def test_already_paid_and_double_payment():
    s, n = moneta_matcher.sparuj([P(vs="9")], [], zaplacene_cisla=[9])
    assert s == [] and "už zaplacená" in n[0][1]
    s, n = moneta_matcher.sparuj([P("a", vs="7"), P("b", vs="7")], [F(7)])
    assert len(s) == 1 and len(n) == 1


# -------------------------------------------------------------------- job

@pytest.fixture
def seeded(conn):
    firma = firmy_repo.create(conn, nazev="Test s.r.o.", zkratka="TST", ico="12345678")
    u = ukony_repo.create(conn, firma_id=firma, datum=TODAY, typ_kod="NOVÉ", celkem=1300, rz="3BR9309")
    ppd_repo.upsert(conn, {"cislo": 20260001, "datum": TODAY, "castka": 1300, "druh": "faktura",
                           "vozidlo": "3BR9309"})
    with conn:
        conn.execute("INSERT INTO ppd_ukony(ppd_cislo, ukon_id) VALUES(20260001, ?)", (u,))
    ppd_links.invalidate()
    return u


def test_run_once_settles_dedupes_and_is_idempotent(conn, seeded):
    batch = [P("a", vs="20260001"), P("b", castka=50, zprava="x")]
    moneta_job.run_once(conn, fetch=lambda since: batch)
    assert ukony_repo.get(conn, seeded)["stav_platby"] == "zaplaceno"
    assert conn.execute("SELECT zaplaceno_dne FROM ppd WHERE cislo=20260001").fetchone()[0] == TODAY
    rows = conn.execute("SELECT tx_id, stav, faktura_cislo FROM moneta_platby ORDER BY tx_id").fetchall()
    assert [tuple(r) for r in rows] == [("a", "sparovano", 20260001), ("b", "ignorovano", None)]
    moneta_job.run_once(conn, fetch=lambda since: batch)
    assert conn.execute("SELECT COUNT(*) FROM moneta_platby").fetchone()[0] == 2
    st = moneta_job.get_stav(conn)
    assert st["auth_failed"] == "0" and st["last_ok"] and st["last_error"] == ""


def test_run_once_since_window(conn):
    seen = []
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    moneta_job.run_once(conn, fetch=lambda s: seen.append(s) or [], now=now)
    assert seen[-1] == "2026-10-13"  # no last_ok: 30 days back
    moneta_job.run_once(conn, fetch=lambda s: seen.append(s) or [], now=datetime(2026, 11, 13, tzinfo=timezone.utc))
    assert seen[-1] == "2026-11-09"  # last_ok - 3 days


def test_auth_error_sets_flag_and_never_raises(conn):
    def boom(since):
        raise mc.MonetaAuthError("HTTP 401")
    moneta_job.run_once(conn, fetch=boom)
    assert moneta_job.get_stav(conn)["auth_failed"] == "1"
    moneta_job.run_once(conn, fetch=lambda s: [])
    assert moneta_job.get_stav(conn)["auth_failed"] == "0"


def test_other_error_recorded_without_raising(conn):
    def boom(since):
        raise RuntimeError("kaboom")
    moneta_job.run_once(conn, fetch=boom)
    st = moneta_job.get_stav(conn)
    assert "kaboom" in st["last_error"] and "last_ok" not in st


# ------------------------------------------------------ scheduling and UI

def test_thread_not_started_without_token(monkeypatch):
    monkeypatch.setattr(config, "MONETA_API_TOKEN", "")
    assert moneta_job.start_background() is None


def test_thread_runs_with_token(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MONETA_API_TOKEN", "tok")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    import threading
    ran = threading.Event()
    t = moneta_job.start_background(run=lambda c: ran.set(), first_delay=0, interval_s=60)
    try:
        assert t is not None and ran.wait(5)
    finally:
        t.stop_event.set()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


def test_ui_hidden_without_token(client, monkeypatch):
    monkeypatch.setattr(config, "MONETA_API_TOKEN", "")
    assert "Banka:" not in client.get("/doklady").get_data(as_text=True)
    assert client.get("/doklady/platby").status_code == 404


def test_ui_status_and_list(client, monkeypatch):
    monkeypatch.setattr(config, "MONETA_API_TOKEN", "tok")
    with client.application.app_context():
        conn = db.get_db()
        moneta_job.run_once(conn, fetch=lambda s: [P("z", castka=77, zprava="záhada", vs="20269999")])
    html = client.get("/doklady").get_data(as_text=True)
    assert "Banka: zkontrolováno" in html and "1 plateb k ručnímu spárování" in html
    page = client.get("/doklady/platby").get_data(as_text=True)
    assert "77 Kč" in page and "žádná odpovídající faktura" in page
    with client.application.app_context():
        moneta_job._set_stav(db.get_db(), auth_failed="1")
    assert "token vypršel" in client.get("/doklady").get_data(as_text=True)


def test_unrelated_credit_is_ignored_but_faktura_like_vs_is_listed():
    from services import moneta_job
    from services.moneta_client import Platba
    from decimal import Decimal
    najem = Platba("t1", "2026-11-12", Decimal("5000"), "CZK", "123", "najem", "")
    preklep = Platba("t2", "2026-11-12", Decimal("1300"), "CZK", "20269999", "", "")
    assert moneta_job._stav(najem, None, moneta_job.NO_MATCH) == "ignorovano"
    assert moneta_job._stav(preklep, None, moneta_job.NO_MATCH) == "nesparovano"
    assert moneta_job._stav(najem, None, "částka nesedí (přišlo 1, faktura 2)") == "nesparovano"
    assert moneta_job._stav(najem, 20260001, "") == "sparovano"


MONETA_REAL_SHAPE = {  # anonymised copy of a real MONETA v4 transaction (2026-11-12)
    "amount": {"currency": "CZK", "value": 1300},
    "bankTransactionCode": {"proprietary": {"code": "10000107000", "issuer": "CNB"}},
    "bookingDate": {"date": "2026-11-12"},
    "creditDebitIndicator": "CRDT",
    "enteredDate": {"date": None},
    "entryDetails": {"transactionDetails": {
        "references": {"clearingSystemReference": "PAYMENT_ORDER_DOMESTIC",
                       "endToEndIdentification": "0020260001",
                       "transactionDescription": "OKAMŽITÁ ÚHRADA "},
        "relatedParties": {
            "creditorAccount": {"identification": {"other": {"identification": "1/0600"}}},
            "debtor": {"name": "NOVAK JAN"},
            "debtorAccount": {"identification": {"other": {"identification": "0 123/0300"}}}},
        "remittanceInformation": {"structured": {"creditorReferenceInformation": {"reference": "VS:0020260001"}},
                                  "unstructured": "VIN TMBJJ7NE5J0123456"}}},
    "entryReference": "0000000001:20261112:00006:261112IPA00004G7UQT",
    "reversalIndicator": False, "status": "BOOK", "valueDate": {"date": "2026-11-12"},
}


def test_parse_real_moneta_shape():
    import copy
    from decimal import Decimal
    from services.moneta_client import _parse_transaction
    p = _parse_transaction(MONETA_REAL_SHAPE)
    assert p.vs == "20260001" and p.castka == Decimal("1300") and p.datum == "2026-11-12"
    assert p.zprava == "VIN TMBJJ7NE5J0123456" and "NOVAK JAN" in p.protiucet
    assert p.id.startswith("0000000001:20261112")
    debit = copy.deepcopy(MONETA_REAL_SHAPE); debit["creditDebitIndicator"] = "DBIT"
    reversed_ = copy.deepcopy(MONETA_REAL_SHAPE); reversed_["reversalIndicator"] = True
    assert _parse_transaction(debit) is None and _parse_transaction(reversed_) is None
