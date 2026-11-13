"""Faktura převodem + QR Platba: SPAYD, číslování, API (druh), PDF."""
from datetime import date

import os

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
def _cisla(d, n, day=date(2026, 1, 1)):
    return [faktura.issue_faktura(str(d), REC, day) for _ in range(n)]


def test_bijection_over_all_9000_codes():
    kody = {faktura.kod_z_poradi(s) for s in range(1, 9001)}
    assert kody == set(range(1000, 10000))


def test_poradi_round_trip():
    for s in range(1, 9001):
        assert faktura.poradi(faktura.cislo_z_poradi(2026, s)) == s
    assert faktura.CISLO_A == 7393 and faktura.CISLO_B == 2718
    with pytest.raises(ValueError):
        faktura.poradi(20260999)


def test_first_numbers_of_2026_documented():
    assert [faktura.cislo_z_poradi(2026, s) for s in range(1, 6)] == [
        20262111, 20269504, 20267897, 20266290, 20264683]


def test_numbers_are_8_digit_year_prefixed_and_not_consecutive(tmp_path):
    out = _cisla(tmp_path, 6)
    assert all(len(str(n)) == 8 and str(n).startswith("2026") for n in out)
    assert all(abs(b - a) > 1 for a, b in zip(out, out[1:]))
    assert len(set(out)) == 6
    assert [faktura.poradi(n) for n in out] == [1, 2, 3, 4, 5, 6]


def test_new_year_starts_its_own_series_and_ppd_series_is_separate(tmp_path):
    d = str(tmp_path)
    assert ppd.reserve_ppd_number_and_log(d, {"date": "x"}) == 1
    assert faktura.issue_faktura(d, REC, date(2026, 3, 1)) == faktura.cislo_z_poradi(2026, 1)
    assert ppd.reserve_ppd_number_and_log(d, {"date": "x"}) == 2
    assert faktura.issue_faktura(d, REC, date(2027, 1, 5)) == faktura.cislo_z_poradi(2027, 1)


def _seed_old_scheme(d, cisla):
    """Založí faktury ze starého schématu (20260001..) přímo do evidence i zálohy."""
    wb, ws = faktura._open(os.path.join(d, faktura.EVIDENCE_NAME), "Faktury", faktura._HEADER)
    wbb, wsb = faktura._open(os.path.join(d, faktura.BACKUP_NAME), "Záloha", faktura._BACKUP_HEADER)
    for n in cisla:
        ws.append([n, "1.1.2026", "8.1.2026", "X", 1, "u", "v"])
        wsb.append([n, "t", "1.1.2026", "8.1.2026", "X", "", "", 1, "u", "v"])
    faktura._atomic_save(wbb, os.path.join(d, faktura.BACKUP_NAME))
    faktura._atomic_save(wb, os.path.join(d, faktura.EVIDENCE_NAME))


def test_skips_pre_existing_old_scheme_numbers(tmp_path):
    d = str(tmp_path)
    _seed_old_scheme(d, [20260001, 20260002, 20260003])
    out = _cisla(tmp_path, 3)
    assert not set(out) & {20260001, 20260002, 20260003}
    assert out == [faktura.cislo_z_poradi(2026, s) for s in (1, 2, 3)]


def test_collision_with_scrambled_number_takes_next_s(tmp_path):
    d = str(tmp_path)
    _seed_old_scheme(d, [faktura.cislo_z_poradi(2026, 1)])     # s=1 už je obsazené
    assert _cisla(tmp_path, 1) == [faktura.cislo_z_poradi(2026, 2)]


def test_numbers_survive_restart_and_ledger_loss(tmp_path):
    d = str(tmp_path)
    prvni = _cisla(tmp_path, 2)
    # „restart": nová volání čtou jen soubory; ztráta ledgeru = zůstává záloha
    (tmp_path / faktura.EVIDENCE_NAME).unlink()
    dalsi = _cisla(tmp_path, 1)[0]
    assert dalsi == faktura.cislo_z_poradi(2026, 3) and dalsi not in prvni
    assert faktura.read_faktura_backup(d)[0]["cislo"] == dalsi


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


def _pdf_strings(pdf: bytes) -> str:
    try:
        import pypdfium2 as pdfium
        page = pdfium.PdfDocument(pdf)[0]
        return page.get_textpage().get_text_range()
    except ImportError:
        import fitz
        return fitz.open(stream=pdf, filetype="pdf")[0].get_text()


def test_pdf_text_no_vystavil_ares_defaults_total_once(monkeypatch):
    monkeypatch.delenv("ISSUER_ADRESA", raising=False)
    monkeypatch.delenv("ISSUER_SPISOVA_ZNACKA", raising=False)
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    rec = dict(PDF_REC, amount=1500)
    text = " ".join(_pdf_strings(faktura_pdf.build_faktura_pdf(rec)).split())
    assert "Vystavil" not in text
    assert "Cacovická 1592/30a, Husovice" in text and "614 00 Brno" in text
    assert "C 106352 vedená u Krajského soudu v Brně" in text
    assert text.count("Celkem k úhradě") == 1
    assert text.count("1 500,00") == 2          # item row + the total
    assert text.count("QR Platba") == 1


def test_issuer_env_overrides_ares_defaults(monkeypatch):
    monkeypatch.setenv("ISSUER_ADRESA", "Jinde 1, Brno")
    monkeypatch.setenv("ISSUER_SPISOVA_ZNACKA", "C 1")
    cfg = faktura.settings()
    assert cfg["adresa"] == "Jinde 1, Brno" and cfg["spisova_znacka"] == "C 1"


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    monkeypatch.setattr(A, "read_firmy", lambda: [])
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
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


def test_api_default_is_faktura_and_explicit_ppd_still_works(api):
    r = _post(api)
    assert r.status_code == 201
    body = r.get_json()
    assert body["druh"] == "faktura" and body["print_url"] == f"/faktura-print/{body['cislo']}"
    p = _post(api, druh="ppd")
    assert p.status_code == 201
    pb = p.get_json()
    assert pb["druh"] == "ppd" and pb["cislo"] == 1
    assert pb["print_url"] == "/ppd-print/1"


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
    assert page.status_code == 200 and page.mimetype == "application/pdf"
    text = " ".join(_pdf_strings(page.data).split())
    assert "Faktura" in text or "FAKTURA" in text.upper()
    assert "Vystavil" not in text
    assert page.headers["Content-Disposition"] == f"inline; filename=faktura_{body['cislo']}.pdf"
    assert "no-store" in page.headers["Cache-Control"]
    # download a sdílení servírují stejné bajty jako tisk
    assert page.data == (api.data / "output" / f"faktura_{body['cislo']}.pdf").read_bytes()
    assert api.get(f"/download/faktura_{body['cislo']}.pdf").data == page.data


def test_api_faktura_idempotent_and_bad_druh(api):
    a = _post(api, druh="faktura").get_json()
    again = api.post("/api/ppd/vystavit", headers={"X-Api-Key": KLIC}, json={
        "prijato_od": "Firma s.r.o.", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidla": ["3BR9309"], "druh": "faktura", "request_id": "r-faktura"})
    assert again.status_code == 200 and again.get_json()["cislo"] == a["cislo"]
    assert _post(api, druh="proforma").status_code == 400


def test_one_letter_words_never_end_a_line():
    import faktura_pdf
    font = faktura_pdf.ppd._ensure_font()
    for width in range(60, 200, 5):
        for ln in faktura_pdf._split("spisová značka C 106352 vedená u Krajského soudu v Brně",
                                     font, 6.5, width):
            assert not ln.endswith((" u", " v")), ln


def test_iban_display_groups_of_four():
    import faktura_pdf
    assert faktura_pdf._iban_display("CZ6508000000192000145399") == "CZ65 0800 0000 1920 0014 5399"
