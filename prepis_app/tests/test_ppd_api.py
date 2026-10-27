"""POST /api/ppd/vystavit — evidence vystaví doklad (PPD) přes žádosti.

Nový doklad v evidenci (2.5, spec ukony_tracker/docs/superpowers/specs/
2026-10-26-doklady-prestavba-design.md, „Kontrakt pro žádosti"): číslo
přiděluje dál jen žádosti, stejně jako u dokladu k žádosti — ledger, PDF,
záloha i push do evidence. Každé číslo je skutečný účetní doklad, proto:
klíč povinný (bez klíče je cesta vypnutá), opakovaný request_id nikdy
nevystaví druhý doklad a nevalidní tělo nesmí sáhnout na číslování.
"""
import os
import threading
from datetime import datetime

import pytest

import app as A
import ppd
import ppd_push
import tracker_push

KLIC = "testovaci-klic-integrace"
URL = "/api/ppd/vystavit"
TELO = {"prijato_od": "JE & NE, spol. s r.o.", "prijato_ico": "44960263",
        "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidla": ["3BR9309", " 3br7164 "], "zpracoval": "David",
        "request_id": "8d0c6f8e-3c41-4a4e-9a51-0d7f2f7d1a11"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Aplikace jako na webu (přihlašovací brána zapnutá), data v tmp, push zachycený."""
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    monkeypatch.setattr(A, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", KLIC)
    monkeypatch.setattr(A, "read_firmy", lambda: [
        {"nazev": "JE & NE, SPOL. S R.O.", "ico": "44960263", "adresa": "Veveří 102, Brno", "psc": "61600"}])
    poslano = []
    monkeypatch.setattr(ppd_push, "push_async", lambda rec, d: poslano.append(rec))
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        c.poslano = poslano
        c.data = tmp_path
        yield c
    A._login_pokusy.clear()


def _post(c, telo=None, klic=KLIC, **kw):
    headers = {} if klic is None else {"X-Api-Key": klic}
    if "data" in kw:
        return c.post(URL, data=kw["data"], headers=headers, content_type="application/json")
    return c.post(URL, json=TELO if telo is None else telo, headers=headers)


def _zadny_doklad(data_dir) -> bool:
    return not ppd.read_ppd_log(str(data_dir)) and not ppd.read_backup(str(data_dir))


# ── Šťastná cesta ────────────────────────────────────────────────────────────

def test_vystavi_doklad_jako_u_zadosti(api):
    r = _post(api)
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    doklad = body["doklad"]
    assert doklad == {
        "cislo": 1, "datum": datetime.now().strftime("%d.%m.%Y"),
        "prijato_od": "JE & NE, SPOL. S R.O.", "prijato_ico": "44960263",
        "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
        "vozidlo": "3BR9309, 3BR7164", "zadost_id": "", "smazano": False,
    }
    assert body["print_url"] == "/ppd-print/1"
    # ledger, záloha, PDF a push — totéž co doklad k žádosti
    assert ppd.read_ppd_log(str(api.data))[0]["cislo"] == 1
    zaloha = ppd.read_backup(str(api.data))[0]
    assert zaloha["spz"] == "3BR9309, 3BR7164" and zaloha["castka"] == 2600
    assert zaloha["adresa"] == "VEVEŘÍ 102, BRNO", "adresa se doplní z uložené firmy podle IČO"
    assert os.path.getsize(api.data / "output" / "ppd_1.pdf") > 1000
    assert api.poslano == [doklad]


def test_tiskova_stranka_doklad_najde(api):
    _post(api)
    api.post("/login", data={"password": "heslo-jen-pro-test"})
    r = api.get("/ppd-print/1")
    assert r.status_code == 200
    assert "3BR9309, 3BR7164" in r.get_data(as_text=True)


def test_cislo_navazuje_na_doklady_z_zadosti(api):
    ppd.reserve_ppd_number_and_log(str(api.data), {"date": "01.10.2026", "payer": "X", "amount": 100,
                                                   "purpose": "P", "vehicle": "1AB2345"})
    assert _post(api).get_json()["doklad"]["cislo"] == 2


def test_jedno_vin_se_tiskne_jako_vin(api):
    r = _post(api, {**TELO, "vozidla": ["tmbjj7ne5j0123456"], "request_id": "vin-1"})
    assert r.status_code == 201
    zaloha = ppd.read_backup(str(api.data))[0]
    assert zaloha["vin"] == "TMBJJ7NE5J0123456" and not zaloha["spz"]
    assert r.get_json()["doklad"]["vozidlo"] == "TMBJJ7NE5J0123456"


def test_volitelna_pole_muzou_chybet(api):
    telo = {k: v for k, v in TELO.items() if k not in ("prijato_ico", "zpracoval", "request_id")}
    r = _post(api, telo)
    assert r.status_code == 201
    assert r.get_json()["doklad"]["prijato_ico"] == ""


# ── Klíč ─────────────────────────────────────────────────────────────────────

def test_obchazi_prihlaseni_ale_ne_klic(api):
    """Bez session projde (volá ho server evidence), bez klíče ne."""
    assert _post(api).status_code == 201


@pytest.mark.parametrize("klic", [None, "", "spatny-klic", KLIC + "x", "klíc"])
def test_spatny_klic_401_a_zadne_cislo(api, klic):
    r = _post(api, klic=klic)
    assert r.status_code == 401
    assert _zadny_doklad(api.data) and api.poslano == []


def test_bez_nastaveneho_klice_je_cesta_vypnuta(api, monkeypatch):
    """Nenastavený klíč nesmí znamenat „otevřeno pro všechny"."""
    monkeypatch.setattr(tracker_push, "UKONY_API_KEY", "")
    for klic in (None, "", "cokoliv"):
        assert _post(api, klic=klic).status_code == 503
    assert _zadny_doklad(api.data)


def test_hadani_klice_se_zabrzdi(api):
    for _ in range(A._LOGIN_MAX_POKUSU):
        _post(api, klic="spatny")
    assert _post(api, klic="spatny").status_code == 429


# ── Idempotence ──────────────────────────────────────────────────────────────

def test_stejny_request_id_nevystavi_druhy_doklad(api):
    prvni = _post(api)
    druhy = _post(api)
    assert prvni.status_code == 201 and druhy.status_code == 200
    assert druhy.get_json() == prvni.get_json()
    assert len(ppd.read_ppd_log(str(api.data))) == 1
    assert len(api.poslano) == 1


def test_ruzne_request_id_jsou_ruzne_doklady(api):
    a = _post(api, {**TELO, "request_id": "a-1"}).get_json()["doklad"]["cislo"]
    b = _post(api, {**TELO, "request_id": "b-2"}).get_json()["doklad"]["cislo"]
    assert (a, b) == (1, 2)


def test_dvojklik_naraz_vystavi_jeden_doklad(api):
    vysledky = []

    def klik():
        with A.app.test_client() as c:
            vysledky.append(c.post(URL, json=TELO, headers={"X-Api-Key": KLIC}).status_code)

    vlakna = [threading.Thread(target=klik) for _ in range(4)]
    for v in vlakna:
        v.start()
    for v in vlakna:
        v.join()
    assert sorted(vysledky) == [200, 200, 200, 201]
    assert len(ppd.read_ppd_log(str(api.data))) == 1


# ── Validace ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("zmena", [
    {"castka": 0}, {"castka": -5}, {"castka": 2.5}, {"castka": "2600"}, {"castka": True},
    {"castka": 10_000_001}, {"castka": None},
    {"prijato_od": ""}, {"prijato_od": "   "}, {"prijato_od": 123}, {"prijato_od": "X" * 201},
    {"ucel": ""}, {"ucel": None}, {"ucel": "U" * 121},
    {"vozidla": []}, {"vozidla": "3BR9309"}, {"vozidla": [""]}, {"vozidla": ["  "]},
    {"vozidla": [123]}, {"vozidla": ["X" * 21]}, {"vozidla": ["1AB2345"] * 31},
    {"prijato_ico": "ABC"}, {"prijato_ico": 44960263}, {"prijato_ico": "1" * 13},
    {"zpracoval": ["David"]}, {"zpracoval": "D" * 61},
    {"request_id": "ne povoleno!"}, {"request_id": "r" * 101}, {"request_id": 5},
    # openpyxl by text začínající „=" zapsal do knihy dokladů jako vzorec
    {"prijato_od": '=HYPERLINK("http://x","klik")'}, {"ucel": "=1+1"}, {"vozidla": ["=A1"]},
])
def test_nevalidni_telo_400_a_zadne_cislo(api, zmena):
    r = _post(api, {**TELO, **zmena})
    assert r.status_code == 400
    assert r.get_json()["error"]
    assert _zadny_doklad(api.data) and api.poslano == []


@pytest.mark.parametrize("vynechat", ["prijato_od", "castka", "ucel", "vozidla"])
def test_chybejici_povinne_pole_400(api, vynechat):
    r = _post(api, {k: v for k, v in TELO.items() if k != vynechat})
    assert r.status_code == 400 and _zadny_doklad(api.data)


@pytest.mark.parametrize("data", ["", "nejson", "[1, 2]", '"text"', "null"])
def test_telo_neni_objekt_400(api, data):
    r = _post(api, data=data)
    assert r.status_code == 400 and _zadny_doklad(api.data)


def test_castka_jako_cele_cislo_v_plovouci_carce_projde(api):
    r = _post(api, {**TELO, "castka": 2600.0, "request_id": "f-1"})
    assert r.status_code == 201 and r.get_json()["doklad"]["castka"] == 2600


# ── Adresa plátce ze žádosti (zadost_id + strana) ────────────────────────────
# Evidence vystaví doklad osobě, pro kterou byla žádost psaná — obvykle nový
# provozovatel, u nového auta je vlastníkem často leasing. Adresa se bere
# z hotové žádosti na disku (prefill.py), nic nového se neukládá. Jméno a IČO
# zůstanou, jak je poslala evidence: uživatel je tam mohl opravit.

import hledani  # noqa: E402
import prefill  # noqa: E402
from pypdf import PdfReader  # noqa: E402

PREVOD_LEASING = {
    "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
    "puvodni_jmeno": "PRODEJCE S.R.O.", "puvodni_ico": "27082440",
    "puvodni_adresa": "STARÁ 1, BRNO", "puvodni_psc": "60200",
    "novy_jmeno": "ČSOB LEASING, A.S.", "novy_ico": "63998980",
    "novy_adresa": "Výmolova 353/3, Praha", "novy_psc": "15000",
    "novy_prov_jiny": True, "novy_prov_jmeno": "JAN NOVÁK",
    "novy_prov_rc_1": "850101", "novy_prov_rc_2": "1234",
    "novy_prov_adresa": "Uzbecká 28, Brno", "novy_prov_psc": "62500",
}
ZADOST_ID = "3f2b8c1e-7d4a-4c6b-9e21-5a0f1b2c3d4e-0a1b2c3d"
ADRESA_PROVOZOVATELE = "UZBECKÁ 28, BRNO, 62500"
ADRESA_LEASINGU = "VÝMOLOVA 353/3, PRAHA, 15000"
ADRESA_FIRMY = "VEVEŘÍ 102, BRNO"     # uložená firma z fixture api (IČO 44960263)


def _ulozena_zadost(data_dir, data=None, kind="zmeny"):
    """Hotová žádost na disku + řádek v indexu — přesně jako po /api/generate."""
    data = PREVOD_LEASING if data is None else data
    out = data_dir / "output"
    out.mkdir(exist_ok=True)
    builder, pdf = {"zmeny": (A.build_zmeny_fields, A.PDF_ZMENY),
                    "zapis": (A.build_zapis_fields, A.PDF_ZAPIS)}[kind]
    name = f"{kind}_NOVAK_1AB2345_20261027.pdf"
    (out / name).write_bytes(A.fill_pdf(pdf, builder(data)))
    hledani.zapis_vystup(str(data_dir), [f"/download/{name}"], {**data, "zadost_id": ZADOST_ID})
    return name


def _s_adresou(strana, **navic):
    return {**TELO, "request_id": f"adr-{strana}", "zadost_id": ZADOST_ID, "strana": strana, **navic}


def _adresa_v_zaloze(api):
    return ppd.read_backup(str(api.data))[0]["adresa"] or ""


def test_adresa_provozovatele_ze_zadosti(api):
    _ulozena_zadost(api.data)
    r = _post(api, _s_adresou("provozovatel"))
    assert r.status_code == 201, r.get_json()
    assert _adresa_v_zaloze(api) == ADRESA_PROVOZOVATELE
    text = PdfReader(str(api.data / "output" / "ppd_1.pdf")).pages[0].extract_text()
    assert "62500" in text, "adresa je i na vytištěném dokladu"


def test_vlastnik_je_novy_vlastnik_ne_prodejce(api):
    _ulozena_zadost(api.data)
    assert _post(api, _s_adresou("vlastnik")).status_code == 201
    assert _adresa_v_zaloze(api) == ADRESA_LEASINGU


def test_jmeno_a_ico_zustanou_jak_je_poslala_evidence(api):
    _ulozena_zadost(api.data)
    r = _post(api, _s_adresou("provozovatel", prijato_od="Jan Novák ml.", prijato_ico=""))
    doklad = r.get_json()["doklad"]
    assert (doklad["prijato_od"], doklad["prijato_ico"]) == ("JAN NOVÁK ML.", "")
    zaloha = ppd.read_backup(str(api.data))[0]
    assert zaloha["prijato_od"] == "JAN NOVÁK ML." and not zaloha["ico"]
    assert zaloha["adresa"] == ADRESA_PROVOZOVATELE


def test_adresa_ze_zadosti_ma_prednost_pred_firmou(api):
    """IČO plátce může mít uloženou firmu — u žádosti platí adresa z tiskopisu."""
    _ulozena_zadost(api.data)
    _post(api, _s_adresou("vlastnik"))   # TELO nese IČO uložené firmy
    assert _adresa_v_zaloze(api) == ADRESA_LEASINGU


def test_provozovatel_bez_jineho_provozovatele_je_vlastnik(api):
    """Bez „jiný provozovatel" provozuje auto vlastník — doklad k žádosti to bere stejně."""
    _ulozena_zadost(api.data, {k: v for k, v in PREVOD_LEASING.items() if not k.startswith("novy_prov")})
    _post(api, _s_adresou("provozovatel"))
    assert _adresa_v_zaloze(api) == ADRESA_LEASINGU


@pytest.mark.parametrize("strana, adresa", [("provozovatel", ADRESA_PROVOZOVATELE),
                                            ("vlastnik", ADRESA_LEASINGU)])
def test_zapis_noveho_vozidla(api, strana, adresa):
    """Zápis má strany „Vlastník"/„Provozovatel" (bez „Nový")."""
    _ulozena_zadost(api.data, {**PREVOD_LEASING, "mode": "zapis"}, kind="zapis")
    _post(api, _s_adresou(strana))
    assert _adresa_v_zaloze(api) == adresa


def test_cela_cesta_od_generovani_zadosti(api, monkeypatch):
    """Žádost vygenerovaná přes /api/generate, doklad z evidence s jejím zadost_id."""
    monkeypatch.setattr(tracker_push, "push_async", lambda data, dd: None)
    api.post("/login", data={"password": "heslo-jen-pro-test"})
    r = api.post("/api/generate", json={**PREVOD_LEASING, "zadost_id": ZADOST_ID})
    assert r.status_code == 200 and r.get_json()["success"]
    assert _post(api, _s_adresou("provozovatel")).status_code == 201
    assert _adresa_v_zaloze(api) == ADRESA_PROVOZOVATELE


@pytest.mark.parametrize("pripad", ["neznama_zadost", "smazane_pdf", "rozbite_pdf", "jen_strana"])
def test_nenalezena_zadost_spadne_na_firmu_podle_ico(api, pripad):
    name = _ulozena_zadost(api.data)
    telo = _s_adresou("provozovatel")
    if pripad == "neznama_zadost":
        telo["zadost_id"] = "jina-zadost"
    elif pripad == "smazane_pdf":
        os.remove(api.data / "output" / name)
    elif pripad == "rozbite_pdf":
        (api.data / "output" / name).write_bytes(b"tohle neni pdf")
    else:
        del telo["zadost_id"]
    r = _post(api, telo)
    assert r.status_code == 201
    assert _adresa_v_zaloze(api) == ADRESA_FIRMY


def test_bez_zadosti_a_bez_ico_je_adresa_prazdna(api):
    r = _post(api, _s_adresou("provozovatel", zadost_id="jina-zadost", prijato_ico=""))
    assert r.status_code == 201
    assert _adresa_v_zaloze(api) == ""


def test_chyba_pri_hledani_zadosti_doklad_neshodi(api, monkeypatch):
    _ulozena_zadost(api.data)

    def rozbite(*a, **k):
        raise RuntimeError("disk")
    monkeypatch.setattr(prefill, "strany", rozbite)
    r = _post(api, _s_adresou("provozovatel"))
    assert r.status_code == 201
    assert _adresa_v_zaloze(api) == ADRESA_FIRMY


@pytest.mark.parametrize("zmena", [
    {"zadost_id": "ne povoleno!"}, {"zadost_id": "z" * 101}, {"zadost_id": 5},
    {"strana": "kupujici"}, {"strana": "vlastník-x"}, {"strana": 1}, {"strana": ["vlastnik"]},
])
def test_nevalidni_zadost_id_nebo_strana_400(api, zmena):
    r = _post(api, {**_s_adresou("provozovatel"), **zmena})
    assert r.status_code == 400 and r.get_json()["error"]
    assert _zadny_doklad(api.data) and api.poslano == []
