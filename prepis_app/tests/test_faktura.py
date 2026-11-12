"""Faktura převodem + QR Platba: SPAYD, číslování, API (druh), PDF."""
from datetime import date

import pytest

import app as A
import faktura
import faktura_pdf
import ppd
import ppd_push
import spayd
import tracker_push

IBAN = "CZ6508000000192000145399"
KLIC = "testovaci-klic-integrace"
REC = {"payer": "FIRMA", "payer_ico": "123", "payer_address": "BRNO", "amount": 2600,
       "purpose": "Zastupování na MMB", "vozidla": ["3BR9309"]}


# ── SPAYD ───────────────────────────────────────────────────────────────────
def test_spayd_shape():
    s = spayd.build_spayd(IBAN, 2600, 20260001, "VIN TMBJJ7NE5J0123456", "ALSETA S.R.O.")
    assert s == ("SPD*1.0*ACC:CZ6508000000192000145399*AM:2600.00*CC:CZK*X-VS:20260001"
                 "*MSG:VIN TMBJJ7NE5J0123456*RN:ALSETA S.R.O.")


@pytest.mark.parametrize("amount,expected", [(1, "1.00"), (2600.5, "2600.50"), ("12.345", "12.35")])
def test_spayd_amount_two_decimals(amount, expected):
    assert f"*AM:{expected}*" in spayd.build_spayd(IBAN, amount, 1)


def test_spayd_sanitises_text_and_caps_lengths():
    s = spayd.build_spayd("cz65 0800 0000 1920 0014 5399", 10, "20260001-x99999999",
                          "Příliš *žluťoučký* 100% kůň " * 5, "Ščř*%" + "A" * 50)
    parts = s.split("*")
    assert "ACC:CZ6508000000192000145399" in parts
    msg = next(p for p in parts if p.startswith("MSG:"))[4:]
    rn = next(p for p in parts if p.startswith("RN:"))[3:]
    assert msg.isascii() and "%" not in msg and len(msg) <= 60
    assert rn.startswith("Scr") and len(rn) <= 35
    assert next(p for p in parts if p.startswith("X-VS:")) == "X-VS:2026000199"


@pytest.mark.parametrize("iban", ["", "123", "CZ12"])
def test_spayd_rejects_bad_iban(iban):
    with pytest.raises(ValueError):
        spayd.build_spayd(iban, 10, 1)


def test_spayd_rejects_non_positive_amount():
    with pytest.raises(ValueError):
        spayd.build_spayd(IBAN, 0, 1)


# ── numbering ───────────────────────────────────────────────────────────────
def test_numbers_yyyynnnn_sequential_and_separate_from_ppd(tmp_path):
    d = str(tmp_path)
    assert ppd.reserve_ppd_number_and_log(d, {"date": "x"}) == 1
    day = date(2026, 3, 1)
    assert faktura.issue_faktura(d, REC, day) == 20260001
    assert faktura.issue_faktura(d, REC, day) == 20260002
    assert ppd.reserve_ppd_number_and_log(d, {"date": "x"}) == 2     # PPD řada se nehnula
    assert faktura.issue_faktura(d, REC, date(2027, 1, 5)) == 20270001


def test_numbers_unique(tmp_path):
    out = [faktura.issue_faktura(str(tmp_path), REC, date(2026, 1, 1)) for _ in range(5)]
    assert out == list(range(20260001, 20260006))


def test_number_never_reused_after_ledger_loss(tmp_path):
    d = str(tmp_path)
    day = date(2026, 6, 1)
    faktura.issue_faktura(d, REC, day)
    last = faktura.issue_faktura(d, REC, day)
    (tmp_path / faktura.EVIDENCE_NAME).unlink()          # „restart" jen se zálohou
    assert faktura.issue_faktura(d, REC, day) == last + 1
    assert [r["cislo"] for r in faktura.read_faktura_backup(d)][:1] == [last + 1]


def test_records_carry_druh_and_ppd_default(tmp_path):
    d = str(tmp_path)
    n = faktura.issue_faktura(d, REC, date(2026, 1, 1))
    assert faktura.read_faktura_log(d)[0]["druh"] == "faktura"
    assert faktura.get_faktura(d, n)["vozidla"] == "3BR9309"
    ppd.reserve_ppd_number_and_log(d, {"date": "x"})
    ppd.append_backup(d, {"cislo": 1})
    assert ppd.read_ppd_log(d)[0]["druh"] == "ppd" and ppd.read_backup(d)[0]["druh"] == "ppd"


def test_due_date_uses_env(monkeypatch):
    monkeypatch.setenv("FAKTURA_SPLATNOST_DNI", "14")
    assert faktura.due_date(date(2026, 1, 1)) == date(2026, 1, 15)
    monkeypatch.setenv("FAKTURA_SPLATNOST_DNI", "blbost")
    assert faktura.due_date(date(2026, 1, 1)) == date(2026, 1, 8)


# ── PDF ─────────────────────────────────────────────────────────────────────
PDF_REC = {"number": 20260001, "date": "1.1.2026", "due": "8.1.2026", "payer": "FIRMA",
           "payer_ico": "123", "payer_address": "BRNO", "amount": 2600,
           "purpose": "Zastupování na MMB", "vozidla": ["TMBJJ7NE5J0123456"]}


def test_pdf_builds_with_and_without_iban(monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    assert faktura_pdf.build_faktura_pdf(PDF_REC).startswith(b"%PDF")
    assert faktura_pdf.spayd_for(PDF_REC, faktura.settings()).endswith("MSG:VIN TMBJJ7NE5J0123456*RN:ALSETA S.R.O.")
    monkeypatch.delenv("FAKTURA_IBAN")
    assert faktura_pdf.build_faktura_pdf(PDF_REC).startswith(b"%PDF")
    assert faktura_pdf.spayd_for(PDF_REC, faktura.settings()) is None


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    monkeypatch.setattr(A, "read_firmy", lambda: [])
    poslano = []
    monkeypatch.setattr(ppd_push, "push_async", lambda rec, d: poslano.append(rec))
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        c.poslano, c.data = poslano, tmp_path
        yield c
    A._login_pokusy.clear()


def _post(c, **extra):
    telo = {"prijato_od": "Firma s.r.o.", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
            "vozidla": ["3BR9309"], "request_id": "r-" + "-".join(extra.values()), **extra}
    return c.post("/api/ppd/vystavit", json=telo, headers={"X-Api-Key": KLIC})


def test_api_default_stays_ppd(api):
    r = _post(api)
    assert r.status_code == 201
    body = r.get_json()
    assert body["druh"] == "ppd" and body["cislo"] == 1
    assert body["print_url"] == "/ppd-print/1" and len(api.poslano) == 1


def test_api_faktura(api):
    r = _post(api, druh="faktura")
    body = r.get_json()
    assert r.status_code == 201 and body["druh"] == "faktura"
    assert 20000000 < body["cislo"] < 30000000 and body["doklad"]["druh"] == "faktura"
    assert body["print_url"] == f"/faktura-print/{body['cislo']}"
    assert (api.data / "output" / f"faktura_{body['cislo']}.pdf").read_bytes().startswith(b"%PDF")
    assert api.poslano == [] and not ppd.read_ppd_log(str(api.data))
    with api.session_transaction() as s:
        s["authed"] = True
    page = api.get(body["print_url"])
    assert page.status_code == 200 and "FAKTURA" in page.get_data(as_text=True)


def test_api_faktura_idempotent_and_bad_druh(api):
    a = _post(api, druh="faktura").get_json()
    again = api.post("/api/ppd/vystavit", headers={"X-Api-Key": KLIC}, json={
        "prijato_od": "Firma s.r.o.", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidla": ["3BR9309"], "druh": "faktura", "request_id": "r-faktura"})
    assert again.status_code == 200 and again.get_json()["cislo"] == a["cislo"]
    assert _post(api, druh="proforma").status_code == 400
