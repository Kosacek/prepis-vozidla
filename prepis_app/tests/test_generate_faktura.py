"""„Hotově / Převodem" v kroku Doklad: převodem se k žádosti vystaví faktura."""
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


def test_prepinac_skryty_bez_iban(client, monkeypatch):
    monkeypatch.delenv("FAKTURA_IBAN", raising=False)
    assert 'id="ppd-platba"' not in client.get("/").get_data(as_text=True)


def test_prepinac_viditelny_s_iban(client, monkeypatch):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    html = client.get("/").get_data(as_text=True)
    assert 'value="hotove" checked' in html and 'value="prevodem"' in html
    assert 'role="radiogroup"' in html


def test_hotove_je_porad_ppd(client, tmp_path, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    for platba in ({}, {"ppd_platba": "hotove"}):
        data = client.post("/api/generate", json=_payload(**platba)).get_json()
        assert data["ppd"].startswith("/download/ppd_")
        assert data["ppd_print"].startswith("/ppd-print/")
        assert "doklad_druh" not in data
    assert not os.path.exists(tmp_path / "faktura_evidence.xlsx")
    assert len(ppd.read_ppd_log(str(tmp_path))) == 2
    assert all("druh" not in b for b in pushes["ppd"])


def test_prevodem_vystavi_fakturu(client, tmp_path, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    r = client.post("/api/generate", json=_payload(ppd_platba="prevodem", ppd_extra_spz="2CD6789"))
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
    assert client.get(data["ppd_print"]).status_code == 200


def test_prevodem_posle_do_evidence_druh_a_splatnost(client, monkeypatch, pushes):
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    data = client.post("/api/generate", json=_payload(ppd_platba="prevodem", zadost_id="zid-1")).get_json()
    assert len(pushes["ppd"]) == 1
    body = pushes["ppd"][0]
    assert body["druh"] == "faktura" and body["cislo"] == data["doklad_cislo"]
    assert body["splatnost"] and body["datum"] and body["zadost_id"] == "zid-1"
    assert body["castka"] == 1300 and body["prijato_od"] == "PETR KUPUJÍCÍ"


def test_prevodem_bez_iban_se_odmitne(client, tmp_path, monkeypatch, pushes):
    monkeypatch.delenv("FAKTURA_IBAN", raising=False)
    r = client.post("/api/generate", json=_payload(ppd_platba="prevodem"))
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False and "chybí číslo účtu" in body["error"]
    assert not os.path.exists(tmp_path / "output")        # nevzniklo nic
    assert not os.path.exists(tmp_path / "faktura_evidence.xlsx")
    assert pushes["ppd"] == [] and pushes["tracker"] == []


def test_neznama_platba_se_odmitne(client):
    assert client.post("/api/generate", json=_payload(ppd_platba="karta")).status_code == 400


def test_build_record_ppd_bez_druhu_faktura_s_druhem():
    base = {"cislo": 1, "date": "01.01.2026", "payer": "X", "amount": 5}
    assert "druh" not in ppd_push.build_record(base) and "splatnost" not in ppd_push.build_record(base)
    fa = ppd_push.build_record({**base, "druh": "faktura", "splatnost": "08.01.2026"})
    assert fa["druh"] == "faktura" and fa["splatnost"] == "08.01.2026"
