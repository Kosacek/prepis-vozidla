"""Sdílená stránka s náhledem + plná moc přilepená ke kódu žádosti (2026-10-14).

Reálný den v provozu: kód s jedním PDF se otevřel rovnou jako PDF (a podle
prohlížeče se rovnou stáhl), kód s víc dokumenty ukázal rozcestník — a nikde
nebylo vidět, CO to je, dokud se to neotevřelo. Navíc plná moc vystavená k
žádosti (Marie K., 3BL8904) dostala pět vlastních kódů místo toho, aby se
přidala ke kódu té žádosti.
"""
import os
import re
from datetime import datetime, timedelta
import io
import json

import pytest

import app as A
import sdileni
from tests.test_sdileni import HTTPS, _cizinec, _generuj, prod  # noqa: F401  (fixture)

WEB = "https://zadosti.spznaklic.cz"


# ── sdileni.pripoj_k_baliku ─────────────────────────────────────────────────

def _pm(jmeno, soubor):
    return {"file": soubor, "kde": sdileni.KDE_OUTPUT, "popis": f"Plná moc — {jmeno}"}


def test_plna_moc_se_prida_ke_kodu_zadosti(tmp_path):
    d = str(tmp_path)
    kod = sdileni.vytvor_kod(d, [{"file": "zmena_X.pdf", "kde": "output", "popis": "Změna"}])
    assert sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("MARIE", "pm_1.pdf")) == kod
    assert [p["file"] for p in sdileni.najdi(d, kod)] == ["zmena_X.pdf", "pm_1.pdf"]


def test_znovu_vystavena_plna_moc_nahradi_tu_predchozi(tmp_path):
    """Pětkrát přegenerovaná plná moc pro stejného člověka = pořád jedna v balíku."""
    d = str(tmp_path)
    kod = sdileni.vytvor_kod(d, [{"file": "zmena_X.pdf", "kde": "output", "popis": "Změna"}])
    for i in range(5):
        sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("MARIE", f"pm_{i}.pdf"))
    sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("JAN", "pm_jan.pdf"))
    assert [p["file"] for p in sdileni.najdi(d, kod)] == ["zmena_X.pdf", "pm_4.pdf", "pm_jan.pdf"]


def test_bez_ziveho_kodu_zadosti_nic_neprilepi(tmp_path):
    d = str(tmp_path)
    sdileni.vytvor_kod(d, [{"file": "jina.pdf", "kde": "output", "popis": ""}])
    assert sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("M", "pm.pdf")) is None


def test_vyprsely_kod_zadosti_se_neobnovi(tmp_path):
    d = str(tmp_path)
    stary = (datetime.now() - timedelta(days=31)).isoformat(timespec="seconds")
    with open(sdileni._cesta(d), "w", encoding="utf-8") as f:
        f.write(json.dumps({"token": "1234", "soubory": ["zmena_X.pdf"], "vytvoreno": stary}) + "\n")
    assert sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("M", "pm.pdf")) is None


def test_prilepeni_neprodlouzi_platnost_kodu(tmp_path):
    d = str(tmp_path)
    puvodne = (datetime.now() - timedelta(days=29, hours=23)).isoformat(timespec="seconds")
    with open(sdileni._cesta(d), "w", encoding="utf-8") as f:
        f.write(json.dumps({"token": "1234", "soubory": ["zmena_X.pdf"], "vytvoreno": puvodne}) + "\n")
    assert sdileni.pripoj_k_baliku(d, "zmena_X.pdf", _pm("M", "pm.pdf")) == "1234"
    posledni = sdileni._nacti(d)[-1]
    assert posledni["vytvoreno"] == puvodne


def test_znovu_pouzity_kod_patri_jen_te_nove_zadosti(tmp_path):
    """Kód 1234 dřív patřil žádosti X; teď patří Y. Plná moc k X se k Y lepit nesmí."""
    d = str(tmp_path)
    stary = (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds")
    novy = datetime.now().isoformat(timespec="seconds")
    with open(sdileni._cesta(d), "w", encoding="utf-8") as f:
        f.write(json.dumps({"token": "1234", "soubory": ["X.pdf"], "vytvoreno": stary}) + "\n")
        f.write(json.dumps({"token": "1234", "soubory": ["Y.pdf"], "vytvoreno": novy}) + "\n")
    assert sdileni.pripoj_k_baliku(d, "X.pdf", _pm("M", "pm.pdf")) is None
    assert [p["file"] for p in sdileni.najdi(d, "1234")] == ["Y.pdf"]


def test_pripoj_nespadne_bez_pristupu_k_disku(tmp_path):
    d = os.path.join(str(tmp_path), "neni", "tu")
    assert sdileni.pripoj_k_baliku(d, "x.pdf", _pm("M", "pm.pdf")) is None


# ── /api/plna-moc vrací kód žádosti ─────────────────────────────────────────

def _strany(prod, soubor):
    return prod.get(f"/api/strany/{soubor}", base_url=WEB, headers=HTTPS).get_json()["strany"]


def test_plna_moc_k_zadosti_dostane_stejny_kod(prod, tmp_path):
    body = _generuj(prod)
    kod = body["sdilet"]
    zadost = body["zmeny"].rsplit("/", 1)[-1]
    role = _strany(prod, zadost)[0]["role"]
    r = prod.post("/api/plna-moc", json={"profil": "David", "zdroj": zadost, "role": role},
                  base_url=WEB, headers=HTTPS).get_json()
    assert r["success"], r
    assert r["sdilet"] == kod
    soubory = [p["file"] for p in sdileni.najdi(str(tmp_path), kod.lstrip("/"))]
    assert soubory == [zadost, r["soubor"]]


def test_plna_moc_k_zadosti_bez_kodu_dostane_kod_i_se_zadosti(prod, tmp_path):
    body = _generuj(prod)
    zadost = body["zmeny"].rsplit("/", 1)[-1]
    os.remove(sdileni._cesta(str(tmp_path)))     # žádost z doby před kódy
    role = _strany(prod, zadost)[0]["role"]
    r = prod.post("/api/plna-moc", json={"profil": "David", "zdroj": zadost, "role": role},
                  base_url=WEB, headers=HTTPS).get_json()
    soubory = [p["file"] for p in sdileni.najdi(str(tmp_path), r["sdilet"].lstrip("/"))]
    assert soubory == [zadost, r["soubor"]]


# ── Stránka s náhledem ──────────────────────────────────────────────────────

def test_i_jeden_dokument_ukaze_stranku_s_nahledem(prod):
    """Už nikdy rovnou PDF — nejdřív vidět, co to je, pak tisknout."""
    body = _generuj(prod)
    kod = body["sdilet"].lstrip("/")
    r = _cizinec(prod).get(body["sdilet"], base_url=WEB, headers=HTTPS)
    assert r.status_code == 200 and r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert f'/{kod}/0/nahled/1' in html
    assert f'href="/{kod}/0"' in html


def test_nahled_je_png_a_jde_bez_prihlaseni(prod):
    body = _generuj(prod)
    kod = body["sdilet"].lstrip("/")
    r = _cizinec(prod).get(f"/{kod}/0/nahled/1", base_url=WEB, headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_nahledy_maji_vsechny_strany_dokumentu(prod):
    body = _generuj(prod)
    kod = body["sdilet"].lstrip("/")
    html = _cizinec(prod).get(body["sdilet"], base_url=WEB, headers=HTTPS).get_data(as_text=True)
    strany = sorted({int(s) for s in re.findall(rf"/{kod}/0/nahled/(\d+)", html)})
    assert strany == list(range(1, len(strany) + 1)) and len(strany) >= 2, strany
    cizi = _cizinec(prod)
    assert cizi.get(f"/{kod}/0/nahled/{len(strany)}", base_url=WEB, headers=HTTPS).status_code == 200
    A._kod_chyby.clear()
    assert cizi.get(f"/{kod}/0/nahled/{len(strany) + 1}", base_url=WEB, headers=HTTPS).status_code == 404
    assert cizi.get(f"/{kod}/0/nahled/0", base_url=WEB, headers=HTTPS).status_code == 404
    A._kod_chyby.clear()


def test_nahled_spatneho_kodu_je_404_a_pocita_se_jako_pokus(prod):
    _generuj(prod)
    A._kod_chyby.clear()
    r = _cizinec(prod).get("/0000/0/nahled/1", base_url=WEB, headers=HTTPS)
    assert r.status_code == 404
    assert A._kod_chyby
    A._kod_chyby.clear()


def test_stahnout_posle_pdf_jako_prilohu(prod):
    body = _generuj(prod)
    kod = body["sdilet"].lstrip("/")
    r = _cizinec(prod).get(f"/{kod}/0?stahnout=1", base_url=WEB, headers=HTTPS)
    assert r.mimetype == "application/pdf"
    assert r.headers["Content-Disposition"].startswith("attachment")
    r = _cizinec(prod).get(f"/{kod}/0", base_url=WEB, headers=HTTPS)
    assert "attachment" not in r.headers.get("Content-Disposition", "")


def test_nahled_se_neda_vyrobit_z_neplatneho_pdf(prod, tmp_path):
    """Rozbité PDF nesmí shodit stránku — dokument jde pořád otevřít."""
    p = os.path.join(str(tmp_path), "output", "zmeny_ROZBITE.pdf")
    with open(p, "wb") as f:
        f.write(b"%PDF-1.4 tohle neni pdf")
    kod = sdileni.vytvor_kod(str(tmp_path), [{"file": "zmeny_ROZBITE.pdf", "kde": "output",
                                             "popis": "Žádost"}])
    r = _cizinec(prod).get(f"/{kod}", base_url=WEB, headers=HTTPS)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f'href="/{kod}/0"' in html and "/nahled/" not in html


# ── Diakritika v náhledu (2026-10-14) ──────────────────────────────────────
# Na serveru (Linux, bez systémových písem) PDFium kreslí pole jen přes
# Helvetica/WinAnsi: z „ŠTĚPÁN ČEŘOVSKÝ" zbylo „ŠT PÁN E OVSKÝ". Hodnoty polí
# proto kreslí nahled.py sám písmem DejaVu Sans.

import nahled

CESKE = "ŠTĚPÁN ČEŘOVSKÝ ĎŇŤ"


@pytest.fixture
def zadost_s_hacky(tmp_path):
    data = {"mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
            "puvodni_jmeno": CESKE, "novy_jmeno": "JIŘÍ ŠŤASTNÝ"}
    p = os.path.join(str(tmp_path), "zmeny_HACKY.pdf")
    with open(p, "wb") as f:
        f.write(A.fill_pdf(A.PDF_ZMENY, A.build_zmeny_fields(data)))
    return p


def _pole_jmena(cesta):
    with open(cesta, "rb") as f:
        _, pole = nahled.bez_textovych_poli(f.read(), 0)
    return next(p for p in pole if p["text"] == CESKE)


def test_textova_pole_se_z_pdfia_vyjmou_i_s_hodnotami(zadost_s_hacky):
    import pypdf, io
    with open(zadost_s_hacky, "rb") as f:
        bez, pole = nahled.bez_textovych_poli(f.read(), 0)
    assert CESKE in [p["text"] for p in pole]
    zbyle = [a.get_object() for a in pypdf.PdfReader(io.BytesIO(bez)).pages[0].get("/Annots") or []]
    assert all(a.get("/FT", a.get("/Parent", {}).get("/FT") if "/Parent" in a else None) != "/Tx"
               for a in zbyle)


def _inkoust(png, rect, vyska_pt):
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    s = nahled.MERITKO
    x0, y0, x1, y1 = rect
    vyrez = im.crop((int(x0 * s), int((vyska_pt - y1) * s), int(x1 * s), int((vyska_pt - y0) * s)))
    return sum(vyrez.point(lambda px: 1 if px < 100 else 0).histogram()[1:])


def test_hacky_v_nahledu_kresli_nase_pismo_ne_pdfium(zadost_s_hacky, monkeypatch):
    pole = _pole_jmena(zadost_s_hacky)
    nahled._png.cache_clear()
    s_textem = nahled.stranka_png(zadost_s_hacky, 1)
    monkeypatch.setattr(nahled, "_dopis_pole", lambda *a, **k: None)
    nahled._png.cache_clear()
    bez_textu = nahled.stranka_png(zadost_s_hacky, 1)
    nahled._png.cache_clear()
    vyska = 841.92
    # Do obdélníku pole zasahuje i tečkovaná linka tiskopisu — proto rozdíl.
    jen_linka = _inkoust(bez_textu, pole["rect"], vyska)
    assert jen_linka < 600, "PDFium pořád kreslí pole sám"
    assert _inkoust(s_textem, pole["rect"], vyska) - jen_linka > 600, "jméno v náhledu chybí"


def test_comb_pole_rozdeli_znaky_do_policek(zadost_s_hacky):
    with open(zadost_s_hacky, "rb") as f:
        _, pole = nahled.bez_textovych_poli(f.read(), 0)
    vin = next(p for p in pole if p["text"] == "TMBEK6NW7M3158470")
    assert vin["comb"] == 17
