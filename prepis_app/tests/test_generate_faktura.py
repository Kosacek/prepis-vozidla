"""Krok „Faktura": doklad k žádosti je vždy faktura (od 1.34.0 žádná volba Hotově/Převodem)."""
import os

import pytest

import app as appmod
import faktura
import ppd
import ppd_push
import tracker_push

IBAN = "CZ6508000000192000145399"


@pytest.fixture(autouse=True)
def pushes(monkeypatch, tmp_path):
    monkeypatch.setattr(appmod, "DATA_DIR", str(tmp_path))
    calls = {"ppd": [], "tracker": []}
    monkeypatch.setattr(ppd_push, "push_async", lambda body, dd: calls["ppd"].append(body))
    monkeypatch.setattr(tracker_push, "push_async", lambda data, dd: calls["tracker"].append(data))
    return calls


def _payload(**over):
    base = {"mode": "prevod", "registracni_znacka": "1AB2345", "vin": "WBA3A5C51DF123456",
            "puvodni_jmeno": "JAN PRODÁVAJÍCÍ", "novy_jmeno": "PETR KUPUJÍCÍ",
            "ppd_castka": "1300", "ppd_prijato_od": "PETR KUPUJÍCÍ", "profil": "David"}
    base.update(over)
    return base


def test_formular_uz_nema_volbu_platby_a_sekce_se_jmenuje_faktura(client, monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    html = client.get("/").get_data(as_text=True)
    for stary in ('name="ppd_platba"', 'id="ppd-platba"', "Doklad (PPD)", "Doklad (faktura)", "ppdPlatba"):
        assert stary not in html
    assert 'id="ppd-card-title">Faktura</div>' in html
    assert "ppd_platba" not in client.get("/static/klavesnice.js").get_data(as_text=True)


def test_bez_ppd_platba_i_s_ni_se_vystavi_faktura_a_ne_ppd(client, tmp_path, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    for platba in ({}, {"ppd_platba": "hotove"}):     # starý klient nic nezmění
        data = client.post("/api/generate", json=_payload(**platba)).get_json()
        assert data["doklad_druh"] == "faktura"
        assert data["ppd"].startswith("/download/faktura_")
        assert data["ppd_print"].startswith("/faktura-print/")
    assert ppd.read_ppd_log(str(tmp_path)) == []
    assert not os.path.exists(tmp_path / "ppd_evidence.xlsx")
    assert len(faktura.read_faktura_log(str(tmp_path))) == 2


def test_prevodem_vystavi_fakturu(client, tmp_path, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    r = client.post("/api/generate", json=_payload(ppd_extra_spz="2CD6789"))
    data = r.get_json()
    assert data["success"] is True
    n = data["doklad_cislo"]
    assert data["doklad_druh"] == "faktura" and n // 10000 == faktura.date.today().year
    assert data["ppd"] == f"/download/faktura_{n}.pdf"
    assert data["ppd_print"] == f"/faktura-print/{n}"
    pdf = tmp_path / "output" / f"faktura_{n}.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    rec = faktura.get_faktura(str(tmp_path), n)
    assert rec["odberatel"] == "PETR KUPUJÍCÍ" and rec["castka"] == 1300
    assert rec["vozidla"] == "1AB2345, 2CD6789"
    assert ppd.read_ppd_log(str(tmp_path)) == []          # žádný PPD
    tisk = client.get(data["ppd_print"])
    assert tisk.status_code == 200 and tisk.mimetype == "application/pdf" and tisk.data.startswith(b"%PDF")
    assert b"Vystavil" not in tisk.data


def test_prevodem_posle_do_evidence_druh_a_splatnost(client, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    data = client.post("/api/generate", json=_payload(zadost_id="zid-1")).get_json()
    assert len(pushes["ppd"]) == 1
    body = pushes["ppd"][0]
    assert body["druh"] == "faktura" and body["cislo"] == data["doklad_cislo"]
    assert body["splatnost"] and body["datum"] and body["zadost_id"] == "zid-1"
    assert body["castka"] == 1300 and body["prijato_od"] == "PETR KUPUJÍCÍ"


def test_bez_iban_se_doklad_odmitne_a_nevznikne_nic(client, tmp_path, monkeypatch, pushes):
    monkeypatch.delenv("FAKTURA_IBAN", raising=False)
    r = client.post("/api/generate", json=_payload())
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False and "chybí číslo účtu" in body["error"]
    assert not os.path.exists(tmp_path / "output")        # nevzniklo nic, ani PPD
    assert not os.path.exists(tmp_path / "faktura_evidence.xlsx")
    assert not os.path.exists(tmp_path / "ppd_evidence.xlsx")
    assert pushes["ppd"] == [] and pushes["tracker"] == []


def test_bez_castky_se_zadny_doklad_nevystavuje_ani_bez_iban(client, monkeypatch):
    monkeypatch.delenv("FAKTURA_IBAN", raising=False)
    data = client.post("/api/generate", json=_payload(ppd_castka="0")).get_json()
    assert data["success"] is True and "ppd" not in data


def test_stary_ppd_se_dal_zobrazi_a_vytiskne(client, tmp_path, monkeypatch):
    n = ppd.reserve_ppd_number_and_log(str(tmp_path), {
        "date": "01.10.2026", "payer": "STARÁ FIRMA", "amount": 500, "purpose": "x", "vehicle": "1AB2345"})
    ppd.append_backup(str(tmp_path), {"cislo": n, "ts": "t", "date": "01.10.2026", "payer": "STARÁ FIRMA",
                                      "payer_ico": "", "payer_address": "", "amount": 500,
                                      "purpose": "x", "spz": "1AB2345", "vin": ""})
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    rows = client.get("/api/ppd-list").get_json()
    assert any(r["cislo"] == n and r["druh"] == "ppd" for r in rows)
    assert "STARÁ FIRMA" in client.get(f"/ppd-print/{n}").get_data(as_text=True)


def test_seznam_dokladu_jde_od_nejnovejsi_faktury_i_pri_nesouvislych_cislech(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    cisla = [client.post("/api/generate", json=_payload()).get_json()["doklad_cislo"] for _ in range(3)]
    fa = [r["cislo"] for r in client.get("/api/ppd-list").get_json() if r["druh"] == "faktura"]
    assert fa == cisla[::-1]


def test_build_record_ppd_bez_druhu_faktura_s_druhem():
    base = {"cislo": 1, "date": "01.01.2026", "payer": "X", "amount": 5}
    assert "druh" not in ppd_push.build_record(base) and "splatnost" not in ppd_push.build_record(base)
    fa = ppd_push.build_record({**base, "druh": "faktura", "splatnost": "08.01.2026"})
    assert fa["druh"] == "faktura" and fa["splatnost"] == "08.01.2026"
