"""Žádost o vydání tabulky s registrační značkou (3rz.pdf) + předvyplnění.

Pole tiskopisu se jmenují nicneříkajícně (fill_2, osoby, comb_4…) a namapovala
se podle pozic widgetů proti natištěným popiskům. Testy proto nekontrolují jen
build_3rz_fields, ale i to, co reálně skončí ve vygenerovaném PDF — překlep
v mapě by jinak poslal IČO do kolonky pro PSČ a nikdo by si toho nevšiml.
"""
import io

import pypdf
import pytest

import app as A
import prefill

DATA = {
    "mode": "3rz",
    "registracni_znacka": "3BR4008",
    "vin": "TMBJJ7NE5J0123456",
    "druh_vozidla": "OSOBNI AUTOMOBIL",
    "novy_jmeno": "AUTO CARDION S. R. O.",
    "novy_adresa": "VEVERKOVA 1234/5, BRNO",
    "novy_psc": "60200",
    "novy_ico": "04156854",
    "novy_rc_1": "",
    "novy_rc_2": "",
}


def _gen(data: dict) -> dict:
    """Vyplní tiskopis a přečte hodnoty zpátky — jako by ho otevřel úředník."""
    raw = A.fill_pdf(A.PDF_3RZ, A.build_3rz_fields(data))
    fields = pypdf.PdfReader(io.BytesIO(raw)).get_fields() or {}
    return {k: str((v or {}).get("/V") or "") for k, v in fields.items()}


# ── mapa polí ─────────────────────────────────────────────────────────────────

def test_vehicle_and_owner_land_in_the_right_boxes():
    f = _gen(DATA)
    assert f["RZ"] == "3BR4008"
    assert f["VIN"] == "TMBJJ7NE5J0123456"
    assert f["Druh vozidla"] == "OSOBNI AUTOMOBIL"
    assert f["fill_2"] == "AUTO CARDION S. R. O."      # jméno vlastníka
    assert f["osoby"] == "VEVERKOVA 1234/5, BRNO"      # adresa vlastníka
    assert f["fill_5"] == "60200"                      # PSČ vlastníka
    assert f["comb_4"] == "04156854"                   # IČO vlastníka


def test_rodne_cislo_is_two_separate_boxes():
    """Tenhle tiskopis má RČ ve dvou kolonkách, ne v jedné s lomítkem jako
    zmena_udaju.pdf — slepení by přeteklo přes okraj."""
    f = _gen(dict(DATA, novy_ico="", novy_rc_1="850101", novy_rc_2="1234"))
    assert f["comb_5"] == "850101"
    assert f["comb_6"] == "1234"
    assert "/" not in f["comb_5"] + f["comb_6"]


def test_default_reason_is_the_carrier_plate():
    """Třetí značka na nosič kol — to je ten běžný případ."""
    f = _gen(DATA)
    assert f["toggle_1"] == "/On"
    assert f["toggle_2"] == "/Off"


def test_damaged_plate_reason_switches_the_box():
    f = _gen(dict(DATA, duvod_3rz="poskozeni"))
    assert f["toggle_1"] == "/Off"
    assert f["toggle_2"] == "/On"


def test_exactly_one_reason_is_ever_ticked():
    for duvod in ("nosic", "poskozeni", "", None):
        f = _gen(dict(DATA, duvod_3rz=duvod))
        ticked = [k for k in ("toggle_1", "toggle_2") if f[k] != "/Off"]
        assert len(ticked) == 1, f"duvod={duvod!r} zaškrtl {ticked}"


def test_provozovatel_blank_when_same_as_owner():
    """Tiskopis říká „vyplnit jen, když je provozovatel odlišný od vlastníka"."""
    f = _gen(DATA)
    for k in ("fill_6", "osoby_2", "fill_9", "comb_3", "comb_1", "undefined"):
        assert f[k] == "", f"{k} má být prázdné"


def test_provozovatel_filled_when_different():
    f = _gen(dict(DATA, novy_prov_jiny=True,
                  novy_prov_jmeno="JAN NOVÁK", novy_prov_adresa="UZBECKÁ 28, BRNO",
                  novy_prov_psc="62500", novy_prov_ico="",
                  novy_prov_rc_1="900202", novy_prov_rc_2="5678"))
    assert f["fill_6"] == "JAN NOVÁK"
    assert f["osoby_2"] == "UZBECKÁ 28, BRNO"
    assert f["fill_9"] == "62500"
    assert f["comb_1"] == "900202" and f["undefined"] == "5678"


def test_registry_record_stays_empty():
    """Horní blok strany 2 je „Záznam registračního místa" — vyplňuje ho úřednice."""
    f = _gen(DATA)
    for k in ("undefined_3", "fill_2_2", "fill_3_2", "fill_4"):
        assert f[k] == "", f"{k} (záznam úřadu) má zůstat prázdné"


def test_second_page_receipt_is_signed_by_the_applicant():
    """Dole na straně 2 je „Potvrzení o převzetí dokladů žadatelem" — to
    podepisuje žadatel, takže tam patří místo i „v z."; datum se doplní až
    při přebírání na úřadě."""
    raw = A.add_vz_fields(A.fill_pdf(A.PDF_3RZ, A.build_3rz_fields(DATA)), "3rz")
    f = {k: str((v or {}).get("/V") or "")
         for k, v in (pypdf.PdfReader(io.BytesIO(raw)).get_fields() or {}).items()}
    assert f["V_2"] == "Brně"
    assert f["dne_2"] == ""
    assert f["vz_podpis_1"] == "v z."      # strana 1
    assert f["vz_podpis_2"] == "v z."      # strana 2


def _vz_rects(doc, template, builder):
    raw = A.add_vz_fields(A.fill_pdf(template, builder(DATA)), doc)
    out = []
    for page in pypdf.PdfReader(io.BytesIO(raw)).pages:
        for a in (page.get("/Annots") or []):
            o = a.get_object()
            if str(o.get("/T", "")).startswith("vz_podpis"):
                out.append([round(float(v)) for v in o["/Rect"]])
    return out


def test_3rz_signature_sits_left_of_the_other_forms():
    """3rz.pdf má popisek „Podpis žadatele" bez „(ů)", takže tečkovaná linka
    začíná dřív a společné x=400 působilo posunuté doprava. Ostatní tiskopisy
    se tím ale hýbat NESMÍ — jsou roky odladěné."""
    trz = _vz_rects("3rz", A.PDF_3RZ, A.build_3rz_fields)
    zmeny = _vz_rects("zmeny", A.PDF_ZMENY, A.build_zmeny_fields)
    assert {r[0] for r in trz} == {385}
    assert {r[0] for r in zmeny} == {400}


def test_place_and_date_filled():
    f = _gen(DATA)
    assert f["V"] == "Brně"          # nesmí se zvelkopísmenit
    assert len(f["dne"]) == 10       # DD.MM.RRRR


# ── předvyplnění z dřívější žádosti ───────────────────────────────────────────

def test_prefill_roundtrip_through_a_real_pdf(tmp_path):
    """Vygenerovanou 3RZ žádost musí jít přečíst zpátky do stejných dat —
    to je přesně to, co dělá „navázat na dřívější žádost"."""
    out = tmp_path / "output"
    out.mkdir()
    raw = A.fill_pdf(A.PDF_3RZ, A.build_3rz_fields(DATA))
    (out / "3rz_20260808_120000.pdf").write_bytes(raw)

    d = prefill.z_pdf(str(tmp_path), "3rz_20260808_120000.pdf")
    assert d["registracni_znacka"] == "3BR4008"
    assert d["vin"] == "TMBJJ7NE5J0123456"
    assert d["novy_jmeno"] == "AUTO CARDION S. R. O."
    assert d["novy_adresa"] == "VEVERKOVA 1234/5, BRNO"
    assert d["novy_psc"] == "60200"
    assert d["novy_ico"] == "04156854"
    assert d["novy_prov_jiny"] is False


def test_prefill_splits_combined_rodne_cislo(tmp_path):
    """zmena_udaju.pdf ukládá RČ jako '850101/1234' v jednom poli — při čtení
    zpátky se musí rozdělit, jinak by 3RZ dostala celý řetězec do první kolonky."""
    out = tmp_path / "output"
    out.mkdir()
    raw = A.fill_pdf(A.PDF_ZMENA, A.build_zmena_fields({
        "registracni_znacka": "1AB2345", "vin": "WVWZZZ3CZDE157718",
        "novy_jmeno": "PETR SVOBODA", "novy_rc_1": "850101", "novy_rc_2": "1234",
        "novy_adresa": "HLAVNÍ 1, BRNO", "novy_psc": "60200",
    }))
    (out / "zmena_20260808_120000.pdf").write_bytes(raw)
    d = prefill.z_pdf(str(tmp_path), "zmena_20260808_120000.pdf")
    assert d["novy_rc_1"] == "850101"
    assert d["novy_rc_2"] == "1234"
    assert d["registracni_znacka"] == "1AB2345"


def test_prefill_reads_the_new_owner_not_the_seller(tmp_path):
    """U převodu navazuje třetí značka na toho, kdo auto dostal."""
    out = tmp_path / "output"
    out.mkdir()
    raw = A.fill_pdf(A.PDF_ZMENY, A.build_zmeny_fields({
        "registracni_znacka": "5C99999", "vin": "TMBEK6NW7M3158470",
        "puvodni_jmeno": "PRODEJCE S.R.O.", "puvodni_adresa": "STARÁ 1, BRNO",
        "novy_jmeno": "KUPUJÍCÍ A.S.", "novy_adresa": "NOVÁ 2, BRNO",
        "novy_psc": "61200", "novy_ico": "27082440",
    }))
    (out / "zmeny_20260808_120000.pdf").write_bytes(raw)
    d = prefill.z_pdf(str(tmp_path), "zmeny_20260808_120000.pdf")
    assert d["novy_jmeno"] == "KUPUJÍCÍ A.S."
    assert d["novy_ico"] == "27082440"
    assert "PRODEJCE" not in str(d)


@pytest.mark.parametrize("bad", ["", "neco.txt", "../../etc/passwd", "3rz_neexistuje.pdf"])
def test_prefill_never_raises_on_bad_input(bad, tmp_path):
    assert prefill.z_pdf(str(tmp_path), bad) == {}


# ── route ─────────────────────────────────────────────────────────────────────

def test_generate_route_produces_the_3rz_pdf(client):
    r = client.post("/api/generate", json=DATA)
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("success") is True
    assert body["3rz"].startswith("/download/3rz_")
    assert "TOYOTA" not in body["3rz"]   # tahle ukázka je Cardion
    assert "AUTO-CARDION" in body["3rz"] and "3BR4008" in body["3rz"]
    assert "zmeny" not in body and "zapis" not in body   # jen tenhle tiskopis


def test_prefill_route(client):
    assert client.get("/api/prefill/nic.pdf").get_json() == {}
