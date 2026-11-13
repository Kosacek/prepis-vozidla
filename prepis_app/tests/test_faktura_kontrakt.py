"""Kontrakt žádosti ↔ evidence pro fakturu: moznosti, 409, ppd-list, sdílení."""
import os
from datetime import date

import pytest

import app as A
import faktura
import ppd_push
import sdileni
import tracker_push

IBAN = "CZ6508000000192000145399"
KLIC = "testovaci-klic-integrace"
H = {"X-Api-Key": KLIC}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    monkeypatch.setattr(A, "read_firmy", lambda: [])
    monkeypatch.setattr(ppd_push, "push_async", lambda rec, d: None)
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        c.data = tmp_path
        yield c
    A._login_pokusy.clear()


def _vystav(c, rid="r1", **extra):
    return c.post("/api/ppd/vystavit", headers=H, json={
        "prijato_od": "Firma s.r.o.", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidla": ["3BR9309"], "request_id": rid, **extra})


# 1. moznosti
def test_moznosti_s_iban(api):
    r = api.get("/api/ppd/moznosti", headers=H)
    assert r.status_code == 200
    assert r.get_json() == {"faktura": True, "splatnost_dni": 7}


@pytest.mark.parametrize("iban", ["", "blbost"])
def test_moznosti_bez_platneho_iban(api, monkeypatch, iban):
    monkeypatch.setenv("FAKTURA_IBAN", iban)
    monkeypatch.setenv("FAKTURA_SPLATNOST_DNI", "14")
    assert api.get("/api/ppd/moznosti", headers=H).get_json() == {
        "faktura": False, "splatnost_dni": 14}


@pytest.mark.parametrize("hlavicky", [{}, {"X-Api-Key": "spatny"}])
def test_moznosti_vyzaduje_klic(api, hlavicky):
    assert api.get("/api/ppd/moznosti", headers=hlavicky).status_code == 401


def test_moznosti_bez_nastaveneho_klice_503(api, monkeypatch):
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "")
    assert api.get("/api/ppd/moznosti", headers=H).status_code == 503


# 2. 409 + čítač
def test_faktura_nedostupna_409_a_cislo_se_nepohne(api, monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", "")
    r = _vystav(api, druh="faktura")
    assert r.status_code == 409 and r.get_json() == {"error": "faktura_nedostupna"}
    for nazev in (faktura.EVIDENCE_NAME, faktura.BACKUP_NAME):
        assert not os.path.exists(api.data / nazev)
    assert not os.path.exists(api.data / "output")
    # po zapnutí IBAN je první číslo řady první, žádné spálené číslo
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    cislo = _vystav(api, rid="r2", druh="faktura").get_json()["cislo"]
    assert cislo == faktura.cislo_z_poradi(date.today().year, 1)


def test_bez_druhu_je_faktura_a_bez_iban_409_explicitni_ppd_jde(api, monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", "")
    assert _vystav(api).status_code == 409                 # výchozí = faktura
    r = _vystav(api, rid="p", druh="ppd")
    assert r.status_code == 201 and r.get_json()["druh"] == "ppd"
    assert "splatnost" not in r.get_json()


def test_uspech_faktury_ma_cislo_splatnost_amount(api):
    b = _vystav(api, druh="faktura").get_json()
    assert b["druh"] == "faktura" and b["amount"] == 2600
    assert len(b["splatnost"]) == 10 and b["splatnost"][2] == "." and b["splatnost"][5] == "."
    assert b["doklad"]["splatnost"] == b["splatnost"]
    # opakování vrací totéž
    assert _vystav(api, druh="faktura").get_json()["splatnost"] == b["splatnost"]


# 3. ppd-list
def test_ppd_list_ma_druh_a_splatnost(api):
    ppd_cislo = _vystav(api, rid="a", druh="ppd").get_json()["cislo"]
    fa = _vystav(api, rid="b", druh="faktura").get_json()
    with api.session_transaction() as s:
        s["authed"] = True
    rows = {r["cislo"]: r for r in api.get("/api/ppd-list").get_json()}
    assert rows[ppd_cislo]["druh"] == "ppd" and "splatnost" not in rows[ppd_cislo]
    assert rows[fa["cislo"]]["druh"] == "faktura"
    assert rows[fa["cislo"]]["splatnost"] == fa["splatnost"]
    assert rows[fa["cislo"]]["prijato_od"] == "FIRMA S.R.O."
    assert rows[fa["cislo"]]["castka"] == 2600


# 4. sdílení
def test_sdilet_faktury_ukaze_fakturu_ne_ppd(api):
    cislo = _vystav(api, druh="faktura").get_json()["cislo"]
    r = api.post(f"/api/ppd/{cislo}/sdilet", headers=H, json={"druh": "faktura"})
    assert r.status_code == 200
    kod = r.get_json()["sdilet"]
    polozky = sdileni.najdi_balik(str(api.data), kod[1:])
    assert polozky == [{"file": f"faktura_{cislo}.pdf", "kde": "output",
                        "popis": f"Faktura č. {cislo}", "druh": "faktura"}]
    page = api.get(kod)
    assert page.status_code == 200 and f"Faktura č. {cislo}" in page.get_data(as_text=True)
    pdf = api.get(f"{kod}/0")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert pdf.data == (api.data / "output" / f"faktura_{cislo}.pdf").read_bytes()
    # idempotentní
    assert api.post(f"/api/ppd/{cislo}/sdilet", headers=H,
                    json={"druh": "faktura"}).get_json()["sdilet"] == kod


def test_sdilet_faktury_postavi_chybejici_pdf_ze_zalohy(api):
    cislo = _vystav(api, druh="faktura").get_json()["cislo"]
    os.remove(api.data / "output" / f"faktura_{cislo}.pdf")
    r = api.post(f"/api/ppd/{cislo}/sdilet", headers=H, json={"druh": "faktura"})
    assert r.status_code == 200
    assert (api.data / "output" / f"faktura_{cislo}.pdf").read_bytes().startswith(b"%PDF")


def test_sdilet_neexistujici_faktura_404_a_spatny_druh_400(api):
    assert api.post("/api/ppd/20269999/sdilet", headers=H,
                    json={"druh": "faktura"}).status_code == 404
    assert api.post("/api/ppd/1/sdilet", headers=H, json={"druh": "x"}).status_code == 400


def test_sdilet_bez_tela_je_stale_ppd(api):
    (api.data / "output").mkdir(exist_ok=True)
    (api.data / "output" / "ppd_7.pdf").write_bytes(b"%PDF-1.4 t")
    kod = api.post("/api/ppd/7/sdilet", headers=H).get_json()["sdilet"]
    pol = sdileni.najdi(str(api.data), kod[1:])
    assert pol[0]["file"] == "ppd_7.pdf" and pol[0]["druh"] == "ppd"


def test_stary_zaznam_kodu_bez_druhu_je_ppd(tmp_path):
    (tmp_path / "share_tokens.jsonl").write_text(
        '{"token": "1234", "soubory": [{"file": "ppd_1.pdf", "kde": "output", "popis": "x"}],'
        ' "vytvoreno": "%s"}\n' % __import__("datetime").datetime.now().isoformat(), encoding="utf-8")
    assert sdileni.najdi(str(tmp_path), "1234")[0]["druh"] == "ppd"
    assert sdileni.popis_souboru("faktura_20260001.pdf") == "Faktura č. 20260001"
