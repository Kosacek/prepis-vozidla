"""Vzorky skenů ORV pro test lokálního OCR (ocr_vzorky.py, 1.37.1).

David 2026-11-22 „Yes, keep 30": příštích 30 fotek ze /api/scan-orv přesně
jak přišly + co z nich přečetl model. Limit 30 platí natrvalo (i po smazání),
po 7 dnech se smažou, jména jsou jen čísla, chyba ukládání sken nikdy neshodí
a složka se přes HTTP neservíruje.
"""
import io
import json
import os
import time

import pytest

import app as A
import ocr_vzorky as V


def _obsah(slozka):
    return sorted(os.listdir(slozka)) if os.path.isdir(slozka) else []


def test_ulozi_presne_30_a_dal_uz_nic(tmp_path):
    for i in range(V.LIMIT):
        assert V.uloz(str(tmp_path), b"jpeg-%d" % i, "image/jpeg", {"i": i}) == f"{i + 1:03d}"
    assert V.uloz(str(tmp_path), b"navic", "image/jpeg", {}) is None
    slozka = tmp_path / V.SLOZKA
    jmena = [j for j in _obsah(slozka) if j[0].isdigit()]
    assert len(jmena) == 2 * V.LIMIT
    assert all(j[:3].isdigit() and j[3] == "." and j.split(".")[1] in ("jpg", "json") for j in jmena)
    assert (slozka / "001.jpg").read_bytes() == b"jpeg-0", "bajty přesně jak přišly"
    meta = json.loads((slozka / "030.json").read_text(encoding="utf-8"))
    assert meta["i"] == 29 and meta["soubor"] == "030.jpg" and meta["mime"] == "image/jpeg"


def test_limit_plati_i_po_smazani_starych(tmp_path):
    for _ in range(V.LIMIT):
        V.uloz(str(tmp_path), b"x", "image/jpeg", {})
    za_8_dni = time.time() + 8 * 24 * 3600
    assert V.uloz(str(tmp_path), b"y", "image/jpeg", {}, now=za_8_dni) is None
    assert [j for j in _obsah(tmp_path / V.SLOZKA) if j[0].isdigit()] == [], "staré se smazaly"


def test_po_7_dnech_se_smazou_novejsi_zustanou(tmp_path):
    V.uloz(str(tmp_path), b"stary", "image/png", {})
    V.uloz(str(tmp_path), b"novy", "image/jpeg", {})
    slozka = tmp_path / V.SLOZKA
    pred_8_dny = time.time() - 8 * 24 * 3600
    for j in ("001.png", "001.json"):
        os.utime(slozka / j, (pred_8_dny, pred_8_dny))
    assert V.uklid(str(tmp_path)) == 2
    assert [j for j in _obsah(slozka) if j[0].isdigit()] == ["002.jpg", "002.json"]
    (slozka / "poznamka.txt").write_text("cizí soubor se nemaže")
    os.utime(slozka / "poznamka.txt", (pred_8_dny, pred_8_dny))
    V.uklid(str(tmp_path))
    assert (slozka / "poznamka.txt").exists()


def test_chyba_ulozeni_nevyhodi(tmp_path):
    soubor = tmp_path / "neni-slozka"
    soubor.write_text("x")
    assert V.uloz(str(soubor), b"x", "image/jpeg", {}) is None
    assert V.uklid(str(tmp_path / "nic")) == 0


@pytest.fixture
def sken(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(A, "_OCR_VZORKY", True)
    monkeypatch.setattr(A, "rotate_180", lambda b64, mime: "OTOCENO")
    monkeypatch.setattr(A, "claude_vision_json", lambda obsah: ({"spz": "3BR9309", "osvedceni_serie": "UBZ",
                                                                  "osvedceni_cislo": "482615"}, {}))
    with A.app.test_client() as c:
        c.data_dir = tmp_path
        yield c


def _posli(c, **form):
    form["image"] = (io.BytesIO(b"\xff\xd8 foto ORV"), "capture.jpg", "image/jpeg")
    return c.post("/api/scan-orv", data=form, content_type="multipart/form-data")


def test_sken_ulozi_vzorek_s_vysledkem_a_casy(sken):
    r = _posli(sken, zachyt="klid m=0.0 s=300 e=0.200")
    assert r.get_json()["success"] is True
    slozka = sken.data_dir / V.SLOZKA
    assert (slozka / "001.jpg").read_bytes() == b"\xff\xd8 foto ORV"
    meta = json.loads((slozka / "001.json").read_text(encoding="utf-8"))
    assert meta["odpoved"]["data"]["osvedceni_cislo"] == "482615"
    assert meta["zachyt"] == "klid m=0.0 s=300 e=0.200" and meta["orv_qr"] is None
    assert {"ocr", "celkem", "pokusy"} <= set(meta["casy_ms"]) and meta["ts"]


def test_chyba_vzorku_neshodi_sken(sken, monkeypatch):
    def rozbite(*a, **k):
        raise OSError("disk plný")
    monkeypatch.setattr(V, "_zapis", rozbite)
    r = _posli(sken)
    assert r.status_code == 200 and r.get_json()["success"] is True


def test_bez_vyslovneho_data_dir_se_nic_neuklada(sken, monkeypatch):
    monkeypatch.setattr(A, "_OCR_VZORKY", False)
    _posli(sken)
    assert not (sken.data_dir / V.SLOZKA).exists()


def test_slozka_se_neservíruje(sken):
    _posli(sken)
    for url in ("/download/ocr_vzorky/001.jpg", "/download/..%2Focr_vzorky%2F001.jpg", "/ocr_vzorky/001.jpg"):
        r = sken.get(url)
        assert r.status_code == 404 or b"foto ORV" not in r.data, url
