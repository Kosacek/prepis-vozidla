"""Jeden kód na fakturu: poslední 4 číslice čísla faktury otevřou fakturu a
všechny žádosti a plné moci k ní. Pravidla: kód = XXXX, celé číslo taky,
obnova drží kód, vypršelé = netrefa, žádné kolize s náhodnými kódy, brzda."""
import json
import os
import shutil
from datetime import date, datetime, timedelta

import pytest

import app as A
import faktura
import hledani
import ppd_push
import sdileni
import tracker_push

IBAN = "CZ6508000000192000145399"
KLIC = "testovaci-klic-integrace"
H = {"X-Api-Key": KLIC}
PDFS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdfs")
ROK = date.today().year


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(A, "PLNE_MOCE_DIR", os.path.join(str(tmp_path), "plne_moce"))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    monkeypatch.setattr(A, "read_firmy", lambda: [])
    monkeypatch.setattr(ppd_push, "push_async", lambda rec, d: None)
    monkeypatch.setenv("FAKTURA_IBAN", IBAN)
    A._kod_reset()
    with A.app.test_client() as c:
        c.data = tmp_path
        yield c
    A._kod_reset()


def _vystav(c, rid, **extra):
    return c.post("/api/ppd/vystavit", headers=H, json={
        "prijato_od": "JE & NE s.r.o.", "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidla": ["3BR9309"], "request_id": rid, **extra})


def _zadost(tmp, zid, rz, ico=None):
    """Žádost vygenerovaná dřív: PDF v output/ + záznam v indexu výstupů."""
    out = tmp / "output"
    out.mkdir(exist_ok=True)
    nazev = f"zmeny_FIRMA_{rz}_20261113_{zid}.pdf"
    shutil.copy(os.path.join(PDFS, "zmeny.pdf"), out / nazev)
    if ico:
        (tmp / "plne_moce").mkdir(exist_ok=True)
        shutil.copy(os.path.join(PDFS, "zmeny.pdf"), tmp / "plne_moce" / f"{ico}.pdf")
    hledani.zapis_vystup(str(tmp), [nazev], {"zadost_id": zid, "registracni_znacka": rz},
                         plne_moce=[ico] if ico else None)
    return nazev


def _stary_radek(data_dir, **radek):
    radek.setdefault("vytvoreno", (datetime.now() - timedelta(days=40)).isoformat(timespec="seconds"))
    with open(sdileni._cesta(str(data_dir)), "a", encoding="utf-8") as f:
        f.write(json.dumps(radek) + "\n")


def _verejne(c, cesta):
    return c.get(cesta, base_url="https://zadosti.spznaklic.cz",
                 headers={"CF-Visitor": '{"scheme":"https"}'})


# ── kód = poslední 4 číslice, celé číslo taky ────────────────────────────────

def test_kod_je_poslednich_ctyri_cislice_cisla_faktury(tmp_path):
    assert sdileni.kod_faktury(20265732) == "5732"
    assert sdileni.zapis_fakturu(str(tmp_path), 20265732) == "5732"


def test_celé_cislo_faktury_taky_otevre_balik(api):
    cislo = _vystav(api, "r1").get_json()["cislo"]
    kod = sdileni.kod_faktury(cislo)
    kratky = _verejne(api, "/" + kod)
    dlouhy = _verejne(api, f"/{cislo}")
    assert kratky.status_code == dlouhy.status_code == 200
    assert f"Faktura č. {cislo}" in dlouhy.get_data(as_text=True)


def test_kratky_kod_je_aktualni_rok_a_v_lednu_i_loni(tmp_path):
    d = str(tmp_path)
    sdileni.zapis_fakturu(d, 20255732)          # loňská faktura
    assert sdileni.najdi_balik(d, "5732", dnes=date(2026, 6, 1)) is None
    assert sdileni.najdi_balik(d, "5732", dnes=date(2026, 1, 15))[0]["file"] == "faktura_20255732.pdf"
    sdileni.zapis_fakturu(d, 20265732)          # letos nalezená má přednost
    assert sdileni.najdi_balik(d, "5732", dnes=date(2026, 1, 15))[0]["file"] == "faktura_20265732.pdf"
    # Celé číslo platí pro každý rok.
    assert sdileni.najdi_balik(d, "20255732", dnes=date(2026, 6, 1)) is not None


# ── platnost 30 dní, obnova drží kód ─────────────────────────────────────────

def test_vyprsela_faktura_je_netrefa(api):
    cislo = _vystav(api, "r1").get_json()["cislo"]
    _stary_radek(api.data, token=str(cislo), faktura=cislo, soubory=[], zadost_ids=[])
    assert sdileni.najdi_balik(str(api.data), sdileni.kod_faktury(cislo)) is None
    assert _verejne(api, "/" + sdileni.kod_faktury(cislo)).status_code == 404
    assert _verejne(api, f"/{cislo}").status_code == 404


def test_obnova_drzi_stejny_kod_a_prodlouzi_platnost(api):
    cislo = _vystav(api, "r1").get_json()["cislo"]
    _stary_radek(api.data, token=str(cislo), faktura=cislo, soubory=[], zadost_ids=[])
    assert sdileni.najdi_balik(str(api.data), sdileni.kod_faktury(cislo)) is None
    r = api.post(f"/api/ppd/{cislo}/sdilet", headers=H, json={"druh": "faktura"})
    assert r.get_json() == {"sdilet": "/" + sdileni.kod_faktury(cislo), "plati_dni": 30}
    assert sdileni.najdi_balik(str(api.data), sdileni.kod_faktury(cislo)) is not None
    r2 = api.post(f"/api/ppd/{cislo}/sdilet", headers=H, json={"druh": "faktura"})
    assert r2.get_json()["sdilet"] == r.get_json()["sdilet"]


def test_obnova_neztrati_pripojene_soubory(tmp_path):
    d = str(tmp_path)
    sdileni.zapis_fakturu(d, 20265732, [{"file": "a.pdf", "kde": "output", "popis": "A"}], ["z1"])
    sdileni.zapis_fakturu(d, 20265732, [], ["z2"])
    zaznam = sdileni._posledni_zaznamy(d)["20265732"]
    assert [p["file"] for p in zaznam["soubory"]] == ["a.pdf"]
    assert zaznam["zadost_ids"] == ["z1", "z2"]


# ── obsah: faktura + všechny žádosti a plné moci všech aut ───────────────────

def test_faktura_na_pet_aut_ukaze_vsech_pet_zadosti_i_plne_moci(api):
    tmp = api.data
    rz = ["1AB0001", "1AB0002", "1AB0003", "1AB0004", "1AB0005"]
    ids = [f"zid{i}" for i in range(5)]
    for i, (z, r) in enumerate(zip(ids, rz)):
        _zadost(tmp, z, r, ico="27082440" if i == 0 else None)
    cislo = _vystav(api, "r1", vozidla=rz, zadost_ids=ids).get_json()["cislo"]
    balik = sdileni.najdi_balik(str(tmp), sdileni.kod_faktury(cislo), A._polozky_zadosti)
    assert balik[0]["file"] == f"faktura_{cislo}.pdf"
    zadosti = [p for p in balik if p["file"].startswith("zmeny_")]
    assert len(zadosti) == 5 and all(r in " ".join(p["popis"] for p in zadosti) for r in rz)
    assert [p for p in balik if p["kde"] == sdileni.KDE_PLNE_MOCE] != []
    # Stránka vypíše každý dokument a nabídne „Vytisknout vše“.
    html = _verejne(api, "/" + sdileni.kod_faktury(cislo)).get_data(as_text=True)
    assert html.count('class="dok"') == 7 and "Vytisknout vše" in html
    for i in range(7):
        assert _verejne(api, f"/{sdileni.kod_faktury(cislo)}/{i}").mimetype == "application/pdf"


def test_vytisknout_vse_je_jedno_pdf_se_vsemi_stranami(api):
    from pypdf import PdfReader
    import io
    tmp = api.data
    _zadost(tmp, "zA", "1AB0001")
    cislo = _vystav(api, "r1", zadost_ids=["zA"]).get_json()["cislo"]
    r = _verejne(api, f"/{sdileni.kod_faktury(cislo)}/vse")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    str_faktury = len(PdfReader(str(tmp / "output" / f"faktura_{cislo}.pdf")).pages)
    str_zadosti = len(PdfReader(os.path.join(PDFS, "zmeny.pdf")).pages)
    assert len(PdfReader(io.BytesIO(r.data)).pages) == str_faktury + str_zadosti


def test_pozdeji_pripojene_ukony_se_pridaji_pri_sdileni(api):
    tmp = api.data
    _zadost(tmp, "zA", "1AB0001")
    _zadost(tmp, "zB", "1AB0002")
    cislo = _vystav(api, "r1", zadost_ids=["zA"]).get_json()["cislo"]
    kod = sdileni.kod_faktury(cislo)
    assert len(sdileni.najdi_balik(str(tmp), kod, A._polozky_zadosti)) == 2
    api.post(f"/api/ppd/{cislo}/sdilet", headers=H, json={"druh": "faktura", "zadost_ids": ["zB"]})
    assert len(sdileni.najdi_balik(str(tmp), kod, A._polozky_zadosti)) == 3


def test_vozidlo_bez_zadosti_ukaze_aspon_fakturu(api):
    cislo = _vystav(api, "r1", zadost_ids=["nezname-id"]).get_json()["cislo"]
    html = _verejne(api, "/" + sdileni.kod_faktury(cislo)).get_data(as_text=True)
    assert html.count('class="dok"') == 1 and f"Faktura č. {cislo}" in html


def test_neplatne_zadost_ids_jsou_400(api):
    assert _vystav(api, "r1", zadost_ids="x").status_code == 400
    assert _vystav(api, "r2", zadost_ids=["a b"]).status_code == 400


def test_faktura_z_konce_zadosti_zna_sve_soubory_primo(api, monkeypatch):
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "")
    r = api.post("/api/generate", json={
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
        "puvodni_jmeno": "PRODEJCE S.R.O.", "novy_jmeno": "KUPUJICI S.R.O.",
        "ppd_castka": "1300", "evidence_log": False})
    body = r.get_json()
    assert body["sdilet"] == "/" + sdileni.kod_faktury(body["doklad_cislo"])
    balik = sdileni.najdi_balik(str(api.data), body["sdilet"][1:])
    assert balik[0]["file"] == f"faktura_{body['doklad_cislo']}.pdf"
    assert any("Žádost" in p["popis"] for p in balik)


# ── kolize ───────────────────────────────────────────────────────────────────

def test_nahodny_kod_nikdy_nerovna_zivemu_kodu_faktury(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(sdileni, "KOD_MIN", 4821)
    monkeypatch.setattr(sdileni, "KOD_MAX", 4822)
    sdileni.zapis_fakturu(d, int(f"{ROK}4821"))
    assert sdileni.vytvor_kod(d, "x.pdf") == "4822"


def test_nahodny_kod_se_vyhne_i_loni_vystavene_fakture(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(sdileni, "KOD_MIN", 4821)
    monkeypatch.setattr(sdileni, "KOD_MAX", 4822)
    sdileni.zapis_fakturu(d, int(f"{ROK - 1}4821"))
    assert sdileni.vytvor_kod(d, "x.pdf") == "4822"


def test_vyprsela_faktura_kod_neblokuje(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(sdileni, "KOD_MIN", 4821)
    monkeypatch.setattr(sdileni, "KOD_MAX", 4821)
    _stary_radek(d, token=f"{ROK}4821", faktura=int(f"{ROK}4821"), soubory=[])
    assert sdileni.vytvor_kod(d, "x.pdf") == "4821"


def test_cislovani_faktur_preskoci_zivy_nahodny_kod(tmp_path):
    d = str(tmp_path)
    prvni = faktura.kod_z_poradi(1)
    sdileni._pripis(d, str(prvni), [])           # živý náhodný kód žádosti
    cislo = faktura.issue_faktura(d, {"payer": "X", "amount": 1, "purpose": "u", "vozidla": []})
    assert cislo % 10000 != prvni
    assert cislo % 10000 == faktura.kod_z_poradi(2)


def test_cislovani_faktur_nepreskakuje_vyprsely_kod(tmp_path):
    d = str(tmp_path)
    prvni = faktura.kod_z_poradi(1)
    _stary_radek(d, token=str(prvni), soubory=[])
    assert faktura.issue_faktura(d, {"payer": "X", "amount": 1, "purpose": "u", "vozidla": []}) % 10000 == prvni


def test_obnova_faktury_s_obsazenym_kratkym_kodem_vrati_cele_cislo(tmp_path):
    """Faktura vypršela, její čtyři číslice mezitím dostala jiná žádost."""
    d = str(tmp_path)
    cislo = int(f"{ROK}4821")
    _stary_radek(d, token=str(cislo), faktura=cislo, soubory=[])
    sdileni._pripis(d, "4821", [{"file": "jina.pdf", "kde": "output", "popis": "", "druh": "ppd"}])
    assert sdileni.zapis_fakturu(d, cislo) == str(cislo)
    assert sdileni.najdi_balik(d, "4821")[0]["file"] == "jina.pdf"          # kód žádosti zůstal
    assert sdileni.najdi_balik(d, str(cislo))[0]["file"] == f"faktura_{cislo}.pdf"


def test_jednotliva_zadost_dal_dostava_nahodny_kod(api):
    """Sdílení jedné žádosti se nemění: náhodný kód, ne číslo faktury."""
    r = api.post("/api/sdilet", json={"soubory": ["x.pdf"]})  # za branou → přesměrování
    assert r.status_code in (302, 401)


# ── brzda ────────────────────────────────────────────────────────────────────

def test_vic_nez_deset_netrefa_blokuje_na_patnact_minut_a_pak_pusti(api, monkeypatch):
    t = [1_000_000.0]
    monkeypatch.setattr(A.time, "time", lambda: t[0])
    stavy = []
    for i in range(10):
        stavy.append(_verejne(api, f"/{1000 + i}").status_code)
    assert stavy == [404] * 10                                  # deset netrefa ještě nic
    assert _verejne(api, "/2000").status_code == 404            # jedenáctá zapíná blok
    blok = _verejne(api, "/2001")
    assert blok.status_code == 429 and "Příliš mnoho pokusů" in blok.get_data(as_text=True)
    assert int(blok.headers["Retry-After"]) <= 900
    t[0] += 14 * 60
    assert _verejne(api, "/2002").status_code == 429            # ještě blokováno
    t[0] += 2 * 60
    assert _verejne(api, "/2003").status_code == 404            # po 15 minutách zase odpovídá


def test_netrefy_starsi_nez_deset_minut_se_nepocitaji(api, monkeypatch):
    t = [1_000_000.0]
    monkeypatch.setattr(A.time, "time", lambda: t[0])
    for i in range(10):
        _verejne(api, f"/{1000 + i}")
        t[0] += 61
    assert _verejne(api, "/3000").status_code == 404


def test_uspesne_otevreni_se_do_limitu_nepocita(api, monkeypatch):
    cislo = _vystav(api, "r1").get_json()["cislo"]
    kod = sdileni.kod_faktury(cislo)
    for _ in range(15):
        assert _verejne(api, "/" + kod).status_code == 200
    assert not A._kod_chyby


def test_blok_je_podle_ip_z_cloudflare(api):
    hlavicky = {"CF-Visitor": '{"scheme":"https"}', "CF-Connecting-IP": "203.0.113.9"}
    for i in range(12):
        api.get(f"/{1000 + i}", base_url="https://zadosti.spznaklic.cz", headers=hlavicky)
    assert api.get("/1500", base_url="https://zadosti.spznaklic.cz", headers=hlavicky).status_code == 429
    jina = {"CF-Visitor": '{"scheme":"https"}', "CF-Connecting-IP": "203.0.113.10"}
    assert api.get("/1500", base_url="https://zadosti.spznaklic.cz", headers=jina).status_code == 404


def test_vyprseny_kod_se_pocita_jako_netrefa(api):
    cislo = _vystav(api, "r1").get_json()["cislo"]
    _stary_radek(api.data, token=str(cislo), faktura=cislo, soubory=[])
    _verejne(api, "/" + sdileni.kod_faktury(cislo))
    assert sum(len(v) for v in A._kod_chyby.values()) == 1
