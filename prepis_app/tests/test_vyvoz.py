"""Žádost o vydání tabulky s registrační značkou na vývoz (vyvoz.pdf).

Tiskopis je ze stejné rodiny jako 3rz.pdf a pole se jmenují stejně nicneříkajícně
(fill_2, osoby 1, comb_4). Nebezpečí je, že se mapa opíše od 3RZ — jenže tenhle
formulář má pole POSUNUTÁ: vlastníkovo rodné číslo je comb_1, ne comb_5, a IČO
comb_4 místo comb_4 u jiného bloku. Testy proto čtou hodnoty zpátky z hotového
PDF, aby se případná záměna projevila hned a ne až na přepážce.
"""
import io
from datetime import datetime

import pypdf
import pytest

import app as A

DATA = {
    "mode": "vyvoz",
    "registracni_znacka": "1AB2345",
    "vin": "TMBEK6NW7M3158470",
    "druh_vozidla": "OSOBNI AUTOMOBIL",
    "novy_jmeno": "AUTO CARDION S. R. O.",
    "novy_adresa": "VEVERKOVA 1234/5, BRNO",
    "novy_psc": "60200",
    "novy_ico": "04156854",
    "vyvoz_platnost": "11.11.2026",
}


def _gen(data: dict) -> dict:
    raw = A.fill_pdf(A.PDF_VYVOZ, A.build_vyvoz_fields(data))
    fields = pypdf.PdfReader(io.BytesIO(raw)).get_fields() or {}
    return {k: str((v or {}).get("/V") or "") for k, v in fields.items()}


def test_vehicle_and_owner_land_in_the_right_boxes():
    f = _gen(DATA)
    assert f["RZ"] == "1AB2345"
    assert f["VIN"] == "TMBEK6NW7M3158470"
    assert f["Druh vozidla"] == "OSOBNI AUTOMOBIL"
    assert f["fill_2"] == "AUTO CARDION S. R. O."     # jméno vlastníka
    assert f["osoby 1"] == "VEVERKOVA 1234/5, BRNO"   # adresa vlastníka
    assert f["fill_6"] == "60200"                     # PSČ vlastníka
    assert f["comb_4"] == "04156854"                  # IČO vlastníka


def test_owner_rodne_cislo_uses_this_form_s_own_boxes():
    """Na 3RZ je RČ vlastníka v comb_5/comb_6, tady v comb_1/undefined —
    opsaná mapa by ho poslala do kolonek provozovatele."""
    f = _gen(dict(DATA, novy_ico="", novy_rc_1="850101", novy_rc_2="1234"))
    assert f["comb_1"] == "850101"
    assert f["undefined"] == "1234"
    assert f["comb_5"] == "" and f["comb_6"] == ""    # to jsou pole provozovatele


def test_export_lines_come_from_the_form():
    """Formulář skládá tři řádky (kdo / adresa / platnost), tiskopis je jen
    rozdělí. Firma se vejde na dva, fyzická osoba potřebuje oba."""
    f = _gen(dict(DATA, vyvoz_radky={
        "l1": "MÜLLER GMBH, DE123456789",
        "l2": "HAUPTSTRASSE 5, MÜNCHEN, NĚMECKO",
        "l3": "S platností do 11.11.2026"}))
    assert f["fill_12"] == "MÜLLER GMBH, DE123456789"
    assert f["fill_13"] == "HAUPTSTRASSE 5, MÜNCHEN, NĚMECKO"
    assert f["fill_14"] == "S PLATNOSTÍ DO 11.11.2026"


def test_natural_person_gets_birth_date_and_full_address():
    """Fyzická osoba se na jeden řádek nevejde — jméno s datem narození zvlášť,
    adresa se státem zvlášť."""
    f = _gen(dict(DATA, vyvoz_radky={
        "l1": "HANS MÜLLER, nar. 03.02.1980",
        "l2": "HAUPTSTRASSE 5, 80331 MÜNCHEN, NĚMECKO",
        "l3": "S platností do 11.11.2026"}))
    assert "NAR. 03.02.1980" in f["fill_12"]
    assert "80331" in f["fill_13"]


def test_validity_falls_back_to_the_third_line():
    """Když formulář řádky nepošle, platnost se doplní sama."""
    f = _gen(dict(DATA, vyvoz_radky=None, vyvoz_osoba="HANS MÜLLER"))
    assert f["fill_12"] == "HANS MÜLLER"
    assert "11.11.2026" in f["fill_14"]


def test_validity_line_stays_empty_when_not_filled():
    """Bez data se nesmí vytisknout holé „S platností do"."""
    f = _gen(dict(DATA, vyvoz_radky=None, vyvoz_platnost=""))
    assert f["fill_14"] == ""


def test_provozovatel_blank_when_same_as_owner():
    f = _gen(DATA)
    for k in ("fill_7", "osoby 1_2", "fill_11", "comb_5", "comb_6", "undefined_2"):
        assert f[k] == "", f"{k} má být prázdné"


def test_provozovatel_filled_when_different():
    f = _gen(dict(DATA, novy_prov_jiny=True, novy_prov_jmeno="JAN NOVÁK",
                  novy_prov_adresa="UZBECKÁ 28, BRNO", novy_prov_psc="62500",
                  novy_prov_rc_1="900202", novy_prov_rc_2="5678"))
    assert f["fill_7"] == "JAN NOVÁK"
    assert f["osoby 1_2"] == "UZBECKÁ 28, BRNO"
    assert f["fill_11"] == "62500"
    assert f["comb_5"] == "900202" and f["comb_6"] == "5678"


def test_registry_record_stays_empty():
    f = _gen(DATA)
    for k in ("undefined_3", "fill_2_2", "fill_3_2", "fill_4"):
        assert f[k] == "", f"{k} (záznam úřadu) má zůstat prázdné"


def test_second_page_receipt_is_signed_by_the_applicant():
    raw = A.add_vz_fields(A.fill_pdf(A.PDF_VYVOZ, A.build_vyvoz_fields(DATA)), "vyvoz")
    f = {k: str((v or {}).get("/V") or "")
         for k, v in (pypdf.PdfReader(io.BytesIO(raw)).get_fields() or {}).items()}
    assert f["V"] == "Brně" and len(f["dne"]) == 10
    assert f["V_2"] == "Brně" and f["dne_2"] == ""
    assert f["vz_podpis_1"] == "v z." and f["vz_podpis_2"] == "v z."


def test_signature_matches_the_3rz_family_position():
    """Stejná rodina tiskopisů — podpis se sází na stejné x jako u 3RZ,
    ne na 400 jako u převodu."""
    raw = A.add_vz_fields(A.fill_pdf(A.PDF_VYVOZ, A.build_vyvoz_fields(DATA)), "vyvoz")
    xs = set()
    for page in pypdf.PdfReader(io.BytesIO(raw)).pages:
        for a in (page.get("/Annots") or []):
            o = a.get_object()
            if str(o.get("/T", "")).startswith("vz_podpis"):
                xs.add(round(float(o["/Rect"][0])))
    assert xs == {385}


# ── route ─────────────────────────────────────────────────────────────────────

def test_generate_route_produces_only_the_export_form(client):
    r = client.post("/api/generate", json=DATA)
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("success") is True
    assert body["vyvoz"].startswith("/download/vyvoz_")
    for jiny in ("zmeny", "zapis", "zmena", "3rz"):
        assert jiny not in body


def test_export_is_searchable_like_other_outputs():
    import hledani
    assert hledani.rozbor_nazvu("vyvoz_AUTO-CARDION_1AB2345_20260811.pdf") == (
        "vyvoz", "2026-08-11", "")
    assert hledani.TYPY["vyvoz"] == "Vývoz"
