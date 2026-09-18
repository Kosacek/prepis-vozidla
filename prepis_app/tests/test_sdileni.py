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
    kod = body["zmeny_sdilet"]
    assert re.fullmatch(r"/\d{4}", kod), f"odkaz má být /1234, je {kod}"


def _cizinec(prod):
    """Nový klient bez session cookie — přesně to, co dostane příjemce
    odkazu poslaného přes SMS/WhatsApp. `prod`'s app/DATA_DIR patch platí
    pro celý proces, takže sdílí stejná data i bez sdílení session."""
    return A.app.test_client()


def test_sdileny_odkaz_funguje_bez_prihlaseni(prod):
    """Celý smysl té funkce: cizí prohlížeč bez session cookie a bez hesla."""
    body = _generuj(prod)
    r = _cizinec(prod).get(body["zmeny_sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
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
    r = _cizinec(prod).get(body["zmeny_sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
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
    r = _cizinec(prod).get(body["zmeny_sdilet"], base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    A._kod_chyby.clear()
