"""Sdílecí odkazy /s/<token> — musí fungovat BEZ přihlášení, ale jen na
přesně ten jeden soubor, jen po omezenou dobu, a jít neuhádnout.
"""
import json
import os
import re
from datetime import datetime, timedelta

import sdileni


def test_kod_je_ctyrmistne_cislo(tmp_path):
    """David ho diktuje a píše rukou — musí to být přesně čtyři číslice."""
    kod = sdileni.vytvor_kod(str(tmp_path), "x.pdf")
    assert len(kod) == 4 and kod.isdigit()


def test_kod_neni_poradovy(tmp_path):
    """Kdyby šly kódy po řadě, stačí napsat 1, 2, 3... a projít všechny
    žádosti, co appka kdy vygenerovala."""
    kody = [int(sdileni.vytvor_kod(str(tmp_path), "x.pdf")) for _ in range(12)]
    assert kody != sorted(kody), "kódy jdou vzestupně — to je řada, ne náhoda"
    rozdily = {b - a for a, b in zip(kody, kody[1:])}
    assert rozdily != {1}, "každý další kód je o 1 větší — čistá řada"


def test_dva_kody_nikdy_neukazuji_na_dve_zadosti_naraz(tmp_path):
    """Kolize by tiše přepsala odkaz na starší žádost."""
    kody = [sdileni.vytvor_kod(str(tmp_path), f"z{i}.pdf") for i in range(60)]
    assert len(set(kody)) == 60
    for i, kod in enumerate(kody):
        assert sdileni.najdi_soubor(str(tmp_path), kod) == f"z{i}.pdf"


def test_vyprsely_kod_jde_zase_pouzit_a_plati_ten_novy(tmp_path):
    """Čísel je jen 9000, takže se po 30 dnech recyklují — pak musí platit
    poslední zápis, ne ten starý vypršelý."""
    _zapis_stary(tmp_path, "4242", 40)
    with open(sdileni._cesta(str(tmp_path)), "a", encoding="utf-8") as f:
        f.write(json.dumps({"token": "4242", "file": "nova.pdf",
                            "vytvoreno": datetime.now().isoformat(timespec="seconds")}) + "\n")
    assert sdileni.najdi_soubor(str(tmp_path), "4242") == "nova.pdf"


def test_vytvor_kod_nespadne_ani_bez_pristupu_k_disku(tmp_path):
    kod = sdileni.vytvor_kod(os.path.join(str(tmp_path), "neexistujici", "hloub"), "x.pdf")
    assert len(kod) == 4 and kod.isdigit()


def test_token_je_dost_dlouhy_a_bezpecny_pro_url():
    token = sdileni.vytvor_token("/nepouzije-se", "x.pdf")
    assert len(token) >= 32
    assert all(c.isalnum() or c in "-_" for c in token)


def test_dva_tokeny_pro_stejny_soubor_jsou_ruzne(tmp_path):
    """Jinak by šlo uhodnout token podle vzoru — musí být pokaždé jiný."""
    a = sdileni.vytvor_token(str(tmp_path), "x.pdf")
    b = sdileni.vytvor_token(str(tmp_path), "x.pdf")
    assert a != b


def test_najde_soubor_pro_cerstvy_token(tmp_path):
    token = sdileni.vytvor_token(str(tmp_path), "zmeny_JAN-NOVAK_1AB2345_20260917.pdf")
    assert sdileni.najdi_soubor(str(tmp_path), token) == "zmeny_JAN-NOVAK_1AB2345_20260917.pdf"


def test_neznamy_token_nic_nenajde(tmp_path):
    sdileni.vytvor_token(str(tmp_path), "x.pdf")
    assert sdileni.najdi_soubor(str(tmp_path), "neexistujici-token") is None


def test_bez_souboru_s_tokeny_vubec_nic_nenajde(tmp_path):
    assert sdileni.najdi_soubor(str(tmp_path), "cokoliv") is None


def _zapis_stary(tmp_path, token, dny_stari):
    vytvoreno = datetime.now() - timedelta(days=dny_stari)
    with open(sdileni._cesta(str(tmp_path)), "a", encoding="utf-8") as f:
        f.write(json.dumps({"token": token, "file": "x.pdf",
                            "vytvoreno": vytvoreno.isoformat(timespec="seconds")}) + "\n")


def test_token_stary_29_dni_jeste_platí(tmp_path):
    _zapis_stary(tmp_path, "tok-29", 29)
    assert sdileni.najdi_soubor(str(tmp_path), "tok-29") == "x.pdf"


def test_token_stary_31_dni_uz_vyprsel(tmp_path):
    _zapis_stary(tmp_path, "tok-31", 31)
    assert sdileni.najdi_soubor(str(tmp_path), "tok-31") is None


def test_poskozeny_radek_se_preskoci_ne_spadne(tmp_path):
    path = sdileni._cesta(str(tmp_path))
    with open(path, "a", encoding="utf-8") as f:
        f.write("{neni to json\n")
    token = sdileni.vytvor_token(str(tmp_path), "dobry.pdf")
    assert sdileni.najdi_soubor(str(tmp_path), token) == "dobry.pdf"


def test_vytvor_token_nikdy_nespadne_ani_bez_pristupu_k_disku(tmp_path):
    """Sdílení je bonus — nesmí shodit samotné generování žádosti."""
    nedosazitelny = os.path.join(str(tmp_path), "neexistujici", "podadresar")
    token = sdileni.vytvor_token(nedosazitelny, "x.pdf")
    assert token  # token se vrátí i když se ho nepodařilo zapsat na disk


# ── Integrace: /s/<token> obchází bránu, /download/ ne ─────────────────────
import pytest

import app as A

HTTPS = {"CF-Visitor": '{"scheme":"https"}'}


@pytest.fixture
def prod(monkeypatch, tmp_path):
    """Appka jako na webu (přihlašovací brána zapnutá), s izolovaným DATA_DIR."""
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    os.makedirs(os.path.join(str(tmp_path), "output"), exist_ok=True)
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        yield c
    A._login_pokusy.clear()


def _generuj(prod):
    # /api/generate je za branou stejně jako zbytek appky — jen /s/<token> ne.
    prod.post("/login", data={"password": "heslo-jen-pro-test"},
              base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    r = prod.post("/api/generate", json={
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
        "puvodni_jmeno": "PRODEJCE S.R.O.", "novy_jmeno": "JAN NOVÁK",
    }, base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    return r.get_json()


def test_generate_vraci_i_sdilecí_odkaz(prod):
    body = _generuj(prod)
    assert body["success"] is True
    kod = body["sdilet"]
    assert re.fullmatch(r"/\d{4}", kod), f"odkaz má být /1234, je {kod}"


def _cizinec(prod):
    """Nový klient bez session cookie — přesně to, co dostane příjemce
    odkazu poslaného přes SMS/WhatsApp. `prod`'s app/DATA_DIR patch platí
    pro celý proces, takže sdílí stejná data i bez sdílení session."""
    return A.app.test_client()


def test_sdileny_odkaz_funguje_bez_prihlaseni(prod):
    """Celý smysl té funkce: cizí prohlížeč bez session cookie a bez hesla."""
    body = _generuj(prod)
    r = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"


def test_download_stejneho_souboru_porad_chce_prihlaseni(prod):
    """Sdílecí odkaz nesmí otevřít bránu pro celou appku — jen pro sebe."""
    body = _generuj(prod)
    filename = body["zmeny"].split("/")[-1]
    r = _cizinec(prod).get(f"/download/{filename}", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 302
    assert r.headers["Location"] == "/login"


def test_neplatny_token_dostane_404_ne_50x(prod):
    r = _cizinec(prod).get("/s/toto-neexistuje", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 404


def test_sdileny_odkaz_nema_bezpecnostni_hlavicky_pro_html(prod):
    """CSP se lepí jen na HTML (viz test_bezpecnost.py) — PDF přes /s/ musí
    dopadnout stejně jako přes /download/, jinak by šlo poznat rozdíl."""
    body = _generuj(prod)
    r = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert "Content-Security-Policy" not in r.headers


def test_ctyrmistny_odkaz_nestini_ostatni_adresy(prod):
    """Route /<kod> sedí hned za doménou — nesmí spolknout /login."""
    r = prod.get("/login", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    r2 = _cizinec(prod).get("/abcd", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r2.status_code in (302, 404)  # ne PDF


def test_projizdeni_vsech_cisel_se_zablokuje(prod):
    """Čtyři číslice je jen 9000 možností — po pár netrefách musí appka
    přestat odpovídat, jinak je projde skript za pár minut."""
    A._kod_chyby.clear()
    c = _cizinec(prod)
    kody = [str(1000 + i) for i in range(A._KOD_MAX_CHYB + 3)]
    stavy = [c.get("/" + k, base_url="https://zadosti.spznaklic.cz", headers=HTTPS).status_code
             for k in kody]
    assert stavy[0] == 404
    assert 429 in stavy, "projíždění všech čísel nic nebrzdí"
    posledni = c.get("/" + kody[-1], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert posledni.status_code == 429
    assert posledni.headers.get("Retry-After")
    A._kod_chyby.clear()


def test_spravny_kod_projde_i_kdyz_nekdo_jiny_zkousel(prod):
    """Brzda nesmí zavřít odkaz tomu, kdo má správné číslo."""
    A._kod_chyby.clear()
    body = _generuj(prod)
    r = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    A._kod_chyby.clear()


# ── Balík: odkaz otevře VŠECHNO, co se vygenerovalo ────────────────────────
# David to formuloval jasně: sdílet jen žádost a plnou moc si nechat v appce
# je k ničemu — protějšek potřebuje vytisknout celý balík.

def _plna_moc(tmp_dir, ico):
    """Položí plnou moc tam, kde ji appka hledá (DATA_DIR/plne_moce/<ico>.pdf)."""
    slozka = os.path.join(tmp_dir, "plne_moce")
    os.makedirs(slozka, exist_ok=True)
    zdroj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "pdfs", "zmeny.pdf")
    with open(zdroj, "rb") as f, open(os.path.join(slozka, f"{ico}.pdf"), "wb") as out:
        out.write(f.read())


def _generuj_balik(prod, tmp_path, monkeypatch):
    """Žádost + plná moc kupujícího + pokladní doklad = tři dokumenty."""
    monkeypatch.setattr(A, "PLNE_MOCE_DIR", os.path.join(str(tmp_path), "plne_moce"))
    _plna_moc(str(tmp_path), "27082440")
    prod.post("/login", data={"password": "heslo-jen-pro-test"},
              base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    r = prod.post("/api/generate", json={
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
        "puvodni_jmeno": "PRODEJCE S.R.O.", "novy_jmeno": "KUPUJICI S.R.O.",
        "novy_ico": "27082440", "ppd_castka": "1300", "evidence_log": False,
    }, base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    return r.get_json()


def test_balik_nese_zadost_plnou_moc_i_doklad(prod, tmp_path, monkeypatch):
    body = _generuj_balik(prod, tmp_path, monkeypatch)
    polozky = sdileni.najdi(str(tmp_path), body["sdilet"].lstrip("/"))
    popisy = " | ".join(p["popis"] for p in polozky)
    assert len(polozky) == 3, popisy
    assert "Žádost" in popisy and "Plná moc" in popisy and "doklad" in popisy


def test_vic_dokumentu_ukaze_rozcestnik_ne_rovnou_pdf(prod, tmp_path, monkeypatch):
    body = _generuj_balik(prod, tmp_path, monkeypatch)
    r = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert "Plná moc" in html and "Žádost" in html


def test_rozcestnik_je_slepa_ulicka_do_appky_nepusti(prod, tmp_path, monkeypatch):
    """Kdo přijde přes sdílený odkaz, nesmí se proklikat do průvodce ani
    generovat nové žádosti — vidí jen dokumenty k tisku."""
    body = _generuj_balik(prod, tmp_path, monkeypatch)
    kod = body["sdilet"].lstrip("/")
    html = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz",
                              headers=HTTPS).get_data(as_text=True)
    for zakazane in ['href="/"', "Nová žádost", "api/generate", "Pokračovat"]:
        assert zakazane not in html, f"rozcestník pouští dál do appky: {zakazane}"
    # Odkazy vedou výhradně na dokumenty toho jednoho balíku.
    odkazy = re.findall(r'href="([^"]+)"', html)
    assert odkazy and all(re.fullmatch(rf"/{kod}/\d+", u) for u in odkazy), odkazy


def test_jednotlive_dokumenty_z_baliku_jdou_otevrit(prod, tmp_path, monkeypatch):
    body = _generuj_balik(prod, tmp_path, monkeypatch)
    kod = body["sdilet"].lstrip("/")
    cizi = _cizinec(prod)
    for i in range(3):
        r = cizi.get(f"/{kod}/{i}", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
        assert r.status_code == 200, i
        assert r.mimetype == "application/pdf", i


def test_jeden_dokument_se_otevre_rovnou_bez_mezistranky(prod):
    """Rozcestník s jediným tlačítkem by byl jen klik navíc."""
    body = _generuj(prod)   # bez plné moci a bez PPD = jeden dokument
    r = _cizinec(prod).get(body["sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"


def test_index_mimo_balik_nic_nevyda(prod, tmp_path, monkeypatch):
    body = _generuj_balik(prod, tmp_path, monkeypatch)
    kod = body["sdilet"].lstrip("/")
    A._kod_chyby.clear()
    r = _cizinec(prod).get(f"/{kod}/99", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 404
    A._kod_chyby.clear()


def test_plna_moc_pres_appku_porad_chce_prihlaseni(prod, tmp_path, monkeypatch):
    """Sdílený balík otevírá plnou moc jen skrz svůj kód — původní cesta
    do appky zůstává za heslem."""
    _generuj_balik(prod, tmp_path, monkeypatch)
    r = _cizinec(prod).get("/plna-moc/27082440", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 302
    assert r.headers["Location"] == "/login"
