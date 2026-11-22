"""/api/scan-orv + `orv_qr` (1.37.0): číslo ORV z QR kódu karty.

Prohlížeč přečte QR z té fotky, kterou posílá (static/js/orv_auto.js), a pošle
ho jako `orv_qr`. Stejné pravidlo jako evidence 2.10.0: QR se vezme jen když
je přesně [A-Z]{3}[0-9]{6}, registr k němu dá VIN, VIN z fotky (je-li) sedí a
čtení fotky je nanejvýš překlep od QR. Jinak se nevyplní nic. Bez `orv_qr`
je odpověď stejná jako dřív.
"""
import io
import json

import pytest

import app as A

QR = "UBZ482615"
VIN = "TMBJJ7NE5J0123456"


@pytest.fixture
def sken(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    stav = {"cteni": [], "registr": {"success": True, "vin": VIN}, "dotazy": []}
    monkeypatch.setattr(A, "rotate_180", lambda b64, mime: "OTOCENO")

    def vision(obsah):
        kandidat = obsah[0]["source"]["data"]
        return dict(stav["cteni"][0 if kandidat != "OTOCENO" else 1]), {}
    monkeypatch.setattr(A, "claude_vision_json", vision)

    def registr(serie, cislo):
        stav["dotazy"].append(serie + cislo)
        return stav["registr"]
    monkeypatch.setattr(A, "lookup_orv", registr)
    with A.app.test_client() as c:
        c.stav, c.data = stav, tmp_path
        yield c


def _posli(c, orv_qr=None, zachyt=None):
    form = {"image": (io.BytesIO(b"jpeg"), "capture.jpg", "image/jpeg")}
    if orv_qr is not None:
        form["orv_qr"] = orv_qr
    if zachyt is not None:
        form["zachyt"] = zachyt
    return c.post("/api/scan-orv", data=form, content_type="multipart/form-data").get_json()


def _foto(orv="UBZ482615", **navic):
    return {"spz": "3BR9309", "osvedceni_serie": orv[:3], "osvedceni_cislo": orv[3:], **navic}


def _kamera_log(c):
    cesta = c.data / A.KAMERA_LOG
    return [json.loads(r) for r in cesta.read_text(encoding="utf-8").splitlines()] if cesta.exists() else []


def test_bez_qr_je_odpoved_beze_zmeny(sken):
    sken.stav["cteni"] = [_foto("UBZ482G15"), {}]
    r = _posli(sken)
    assert r == {"success": True, "data": _foto("UBZ482G15")}
    assert sken.stav["dotazy"] == [] and _kamera_log(sken) == []


@pytest.mark.parametrize("spatne", ["ubz482615", "UBZ48261", "UBZ4826150", " UBZ482615", "UBZ482615 ", "0BZ482615", ""])
def test_nevalidni_qr_se_ignoruje(sken, spatne):
    sken.stav["cteni"] = [_foto(), {}]
    assert _posli(sken, spatne) == {"success": True, "data": _foto()}
    assert sken.stav["dotazy"] == []


def test_qr_shodny_s_fotkou_doplni_vin_z_registru(sken):
    sken.stav["cteni"] = [_foto(), {}]
    r = _posli(sken, QR, "klid m=1.0 s=250 e=0.090")
    assert r["success"] is True
    d = r["data"]
    assert (d["osvedceni_serie"], d["osvedceni_cislo"], d["orv_zdroj"]) == ("UBZ", "482615", "qr")
    assert (d["vin"], d["vin_zdroj"]) == (VIN, "registr")
    assert sken.stav["dotazy"] == [QR]
    log = _kamera_log(sken)
    assert [(z["udalost"], z["detail"]) for z in log] == [
        ("orv_qr", "qr=UBZ482615 foto=UBZ482615 vysledek=pouzito zachyt=klid m=1.0 s=250 e=0.090")]


def test_preklep_na_fotce_opravi_qr(sken):
    sken.stav["cteni"] = [_foto("UBZ48Z6I5"), {}]
    d = _posli(sken, QR)["data"]
    assert d["osvedceni_serie"] + d["osvedceni_cislo"] == QR


def test_jine_cislo_na_fotce_nevyplni_nic(sken):
    sken.stav["cteni"] = [_foto("UBE037263"), {}]
    r = _posli(sken, QR)
    assert r == {"success": False, "error": A.QR_CONFLICT, "qr": QR}
    assert sken.stav["dotazy"] == []
    assert "vysledek=nesedi" in _kamera_log(sken)[0]["detail"]


def test_registr_bez_vin_nevyplni_nic(sken):
    sken.stav["cteni"] = [_foto(), {}]
    sken.stav["registr"] = {"success": False, "error": "Vozidlo nenalezeno"}
    assert _posli(sken, QR) == {"success": False, "error": A.QR_NO_VIN, "qr": QR}


def test_jiny_vin_na_fotce_nevyplni_nic(sken):
    sken.stav["cteni"] = [_foto(vin="WF0FXXTTFF7C64192"), {}]
    assert _posli(sken, QR)["error"] == A.QR_CONFLICT


def test_stejny_vin_na_fotce_zustane_z_fotky(sken):
    sken.stav["cteni"] = [_foto(vin=VIN), {}]
    d = _posli(sken, QR)["data"]
    assert d["vin"] == VIN and "vin_zdroj" not in d


def test_fotka_bez_cisla_orv_vezme_qr(sken):
    sken.stav["cteni"] = [{"spz": "3BR9309"}, {}]
    d = _posli(sken, QR)["data"]
    assert d["osvedceni_serie"] + d["osvedceni_cislo"] == QR and d["vin"] == VIN


def test_neni_to_orv_qr_se_nepouzije(sken):
    sken.stav["cteni"] = [{}, {}]
    assert _posli(sken, QR) == {"success": True, "data": {}}
    assert sken.stav["dotazy"] == []
    assert "vysledek=jiny_doklad" in _kamera_log(sken)[0]["detail"]


def test_qr_plati_i_pro_otocenou_fotku(sken):
    sken.stav["cteni"] = [{}, _foto()]
    d = _posli(sken, QR)["data"]
    assert d["orv_zdroj"] == "qr"


def test_zachyt_se_v_logu_ocisti(sken):
    sken.stav["cteni"] = [_foto(), {}]
    _posli(sken, QR, 'qr m=0.5 s=300 e=0.1"<script>' + "x" * 200)
    detail = _kamera_log(sken)[0]["detail"]
    assert "<" not in detail and '"' not in detail and len(detail) < 200
