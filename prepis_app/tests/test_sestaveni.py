"""Sestavení tiskopisu na jeden průchod + udržování v teple.

Vzniklo z reálné stížnosti (2026-09-21): žádost s PPD se generovala 10–15 s.
Měření v produkčním kontejneru ukázalo dvě různé příčiny:

1. PDF se rozebíralo a skládalo TŘIKRÁT (vyplnit → ID → „v z."), každý
   průchod ~0,6 s na ARM procesoru NASky. `sestav_zadost` to dělá napoprvé.
2. Worker měl 15 MB v paměti a 33 MB ve swapu — po pauze se musel celý
   načíst z disku. Na to je `start_zahrivani`.

Tyhle testy hlídají hlavně to, že zrychlení NEZMĚNILO výsledný papír.
"""
import io

import pytest
from pypdf import PdfReader

import app as A

DATA = {
    "mode": "prevod",
    "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
    "puvodni_jmeno": "PRODEJCE S.R.O.", "puvodni_id": "12345",
    "novy_jmeno": "KUPUJICI S.R.O.", "novy_id": "67890",
}
OVERLAYS = [(0, 554, 628, "ID: 12345"), (1, 554, 545, "ID: 67890")]


def _pole(pdf_bytes):
    """Jméno → hodnota všech vyplněných polí formuláře."""
    r = PdfReader(io.BytesIO(pdf_bytes))
    return {k: str(v.get("/V", "")) for k, v in (r.get_fields() or {}).items()}


def _text(pdf_bytes):
    r = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() or "" for p in r.pages)


@pytest.fixture(scope="module")
def postaru():
    """Původní tři průchody po bajtech — referenční výsledek."""
    b = A.fill_pdf(A.PDF_ZMENY, A.build_zmeny_fields(DATA))
    b = A.add_id_overlay(b, OVERLAYS)
    return A.add_vz_fields(b, "zmeny")


@pytest.fixture(scope="module")
def ponovu():
    return A.sestav_zadost(A.PDF_ZMENY, A.build_zmeny_fields(DATA), OVERLAYS, "zmeny")


def test_jeden_pruchod_vyplni_uplne_stejna_pole(postaru, ponovu):
    """Nejdůležitější test celé optimalizace: papír musí být stejný."""
    assert _pole(ponovu) == _pole(postaru)


def test_jeden_pruchod_ma_stejny_pocet_stran(postaru, ponovu):
    assert len(PdfReader(io.BytesIO(ponovu)).pages) == len(PdfReader(io.BytesIO(postaru)).pages)


def test_id_uradu_zustalo_na_papire(ponovu):
    """ID se dokresluje reportlabem — nesmí se po sloučení ztratit."""
    assert "ID: 12345" in _text(ponovu)
    assert "ID: 67890" in _text(ponovu)


def test_vz_podpisy_zustaly(ponovu):
    """„v z." jsou skutečná editovatelná pole, ne natištěný text."""
    pole = _pole(ponovu)
    vz = {k: v for k, v in pole.items() if k.startswith("vz_podpis_")}
    assert len(vz) == len(A.VZ_SIGNATURE_YS["zmeny"])
    assert set(vz.values()) == {A.VZ_TEXT}


def test_bez_overlayu_se_id_vrstva_vubec_nedela():
    """Bez ID nemá smysl volat reportlab — a hlavně se nesmí nic rozbít."""
    b = A.sestav_zadost(A.PDF_ZMENY, A.build_zmeny_fields(DATA), [], "zmeny")
    assert _pole(b)["fill_2"]
    assert "ID:" not in _text(b)


def test_pokazene_vz_nezabrani_vzniku_zadosti(monkeypatch):
    """„v z." je pohodlí, ne podmínka — když selže, žádost musí stejně vzniknout."""
    def _rozbij(*a, **kw):
        raise RuntimeError("simulovaná chyba")
    monkeypatch.setattr(A, "_vloz_vz", _rozbij)
    b = A.sestav_zadost(A.PDF_ZMENY, A.build_zmeny_fields(DATA), [], "zmeny")
    assert _pole(b)["fill_2"]


# ── zahřívání ──────────────────────────────────────────────────────────────

def test_zahrivani_nic_nezapisuje_na_disk(tmp_path, monkeypatch):
    """Běží na pozadí každých pár minut — nesmí plodit soubory ani úkony."""
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    A._zahrej()
    assert list(tmp_path.iterdir()) == []


def test_zahrivani_nikdy_neshodi_worker(monkeypatch):
    def _rozbij(*a, **kw):
        raise RuntimeError("simulovaná chyba")
    monkeypatch.setattr(A, "sestav_zadost", _rozbij)
    A._zahrej()   # nesmí vyhodit


def test_zahrivani_se_nespusti_dvakrat(monkeypatch):
    """Gunicorn importuje app.py v každém workeru — v jednom procesu ale
    stačí jedno vlákno."""
    monkeypatch.setattr(A, "_zahrivani_bezi", False)
    zalozena = []
    monkeypatch.setattr(A.threading, "Thread",
                        lambda *a, **kw: zalozena.append(kw.get("name")) or _FakeThread())
    A.start_zahrivani(150)
    A.start_zahrivani(150)
    assert zalozena == ["zahrivani"]


def test_zahrivani_jde_vypnout(monkeypatch):
    """ZAHRIVANI_S=0 ho úplně umlčí (kdyby na NASce došel procesor)."""
    monkeypatch.setattr(A, "_zahrivani_bezi", False)
    zalozena = []
    monkeypatch.setattr(A.threading, "Thread",
                        lambda *a, **kw: zalozena.append(kw.get("name")) or _FakeThread())
    A.start_zahrivani(0)
    assert zalozena == []


class _FakeThread:
    def start(self):
        pass
