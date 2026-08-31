"""Plná moc k zastupování na registru vozidel.

Zmocněnec je v šabloně natištěný napevno, takže se nedá splést jménem — zato
se dá splést STRANOU: plná moc vystavená na prodávajícího místo na kupujícího
je k ničemu a pozná se to až na přepážce. Proto testy jedou přes reálně
vyplněné žádosti a kontrolují, co skončí v polích šablony.
"""
import io
import os

import pypdf
import pytest

import app as A
import pm
import prefill

PREVOD = {
    "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
    "puvodni_jmeno": "PRODEJCE S.R.O.", "puvodni_ico": "27082440",
    "puvodni_adresa": "STARÁ 1, BRNO", "puvodni_psc": "60200",
    "novy_jmeno": "JAN NOVÁK", "novy_rc_1": "850101", "novy_rc_2": "1234",
    "novy_adresa": "UZBECKÁ 28, BRNO", "novy_psc": "62500",
}


@pytest.fixture
def zadost(tmp_path):
    """Hotový převod na disku — přesně to, z čeho se plná moc vystavuje."""
    out = tmp_path / "output"
    out.mkdir()
    (out / "zmeny_PRODEJCE_1AB2345_20260808.pdf").write_bytes(
        A.fill_pdf(A.PDF_ZMENY, A.build_zmeny_fields(PREVOD)))
    return str(tmp_path), "zmeny_PRODEJCE_1AB2345_20260808.pdf"


# ── strany ────────────────────────────────────────────────────────────────────

def test_both_parties_are_offered(zadost):
    d, f = zadost
    info = prefill.strany(d, f)
    role = [s["role"] for s in info["strany"]]
    assert "Původní vlastník" in role and "Nový vlastník" in role


def test_company_gets_ico_person_gets_rodne_cislo(zadost):
    """Šablona má jednu kolonku „RČ/IČ" — u firmy patří IČO, u osoby RČ."""
    d, f = zadost
    strany = {s["role"]: s for s in prefill.strany(d, f)["strany"]}
    assert strany["Původní vlastník"]["rc_ic"] == "27082440"        # firma
    assert strany["Nový vlastník"]["rc_ic"] == "850101/1234"        # osoba


def test_address_includes_psc(zadost):
    d, f = zadost
    strany = {s["role"]: s for s in prefill.strany(d, f)["strany"]}
    assert strany["Nový vlastník"]["adresa"] == "UZBECKÁ 28, BRNO, 62500"


def test_vehicle_comes_from_the_same_zadost(zadost):
    d, f = zadost
    assert prefill.strany(d, f)["vozidlo"] == {
        "rz": "1AB2345", "vin": "TMBEK6NW7M3158470"}


def test_unfilled_parties_are_skipped(zadost):
    """Provozovatelé v téhle žádosti vyplnění nejsou — nesmí se nabízet."""
    d, f = zadost
    assert not any("provozovatel" in s["role"].lower()
                   for s in prefill.strany(d, f)["strany"])


def test_plna_moc_is_not_a_source(tmp_path):
    """Plnou moc nejde použít jako zdroj pro další plnou moc."""
    (tmp_path / "output").mkdir()
    assert prefill.strany(str(tmp_path), "pm_JAN-NOVAK_20260808.pdf")["strany"] == []


# ── vyplnění šablony ──────────────────────────────────────────────────────────

def _fill(profil, strana, vozidlo=None):
    tpl = pm.sablona(A.BASE_DIR, profil)
    assert tpl, f"šablona pro {profil} chybí"
    path, meta = tpl
    raw = A.fill_pdf(path, pm.build_fields(strana, vozidlo))
    fields = pypdf.PdfReader(io.BytesIO(raw)).get_fields() or {}
    return {k: str((v or {}).get("/V") or "") for k, v in fields.items()}, meta


def test_david_template_carries_person_and_vehicle(zadost):
    d, f = zadost
    info = prefill.strany(d, f)
    strana = next(s for s in info["strany"] if s["role"] == "Nový vlastník")
    fields, meta = _fill("David", strana, info["vozidlo"])
    assert fields[pm.POLE["zmocnitel"]] == "JAN NOVÁK"
    assert fields[pm.POLE["rc_ic"]] == "850101/1234"
    assert "UZBECKÁ 28" in fields[pm.POLE["adresa"]]
    assert fields[pm.POLE["rz"]] == "1AB2345"
    assert fields[pm.POLE["vin"]] == "TMBEK6NW7M3158470"
    assert meta["kdo"] == "David Kosek"


def test_vehicle_left_out_when_not_requested(zadost):
    d, f = zadost
    strana = next(s for s in prefill.strany(d, f)["strany"] if s["role"] == "Nový vlastník")
    fields, _ = _fill("David", strana, None)
    assert fields[pm.POLE["rz"]] == "" and fields[pm.POLE["vin"]] == ""
    assert fields[pm.POLE["zmocnitel"]] == "JAN NOVÁK"


def test_petr_template_has_no_vehicle_boxes():
    """Petrova šablona kolonky na RZ/VIN nemá — nesmí se předstírat, že jo."""
    tpl = pm.sablona(A.BASE_DIR, "Petr")
    assert tpl and tpl[1]["ma_vozidlo"] is False
    fields, meta = _fill("Petr", {"jmeno": "X", "rc_ic": "1", "adresa": "Y"})
    assert meta["kdo"] == "Petr Kosek"
    assert pm.POLE["rz"] not in fields


def test_date_is_today_not_the_zadost_date():
    """Žádosti se post-datují na nejbližší pracovní den, plná moc se ale
    podepisuje ten den, kdy ji vyplňuješ."""
    from datetime import datetime
    fields, _ = _fill("David", {"jmeno": "X", "rc_ic": "1", "adresa": "Y"})
    assert fields[pm.POLE["datum"]] == datetime.now().strftime("%d.%m.%Y")
    assert fields[pm.POLE["datum"]] != A._next_working_day()


def test_unknown_profil_has_no_template():
    """Roman zatím šablonu nemá — radši to přiznat než použít cizí jméno
    na dokumentu, který jde na úřad."""
    assert pm.sablona(A.BASE_DIR, "Roman") is None
    assert pm.sablona(A.BASE_DIR, "") is None


# ── route ─────────────────────────────────────────────────────────────────────

def test_route_rejects_profil_without_template(client):
    r = client.post("/api/plna-moc", json={"profil": "Roman", "zdroj": "x", "role": "y"})
    assert r.status_code == 400
    assert "šablonu" in r.get_json()["error"]


def test_route_rejects_unknown_party(client):
    r = client.post("/api/plna-moc", json={"profil": "David", "zdroj": "nic.pdf", "role": "Kdokoliv"})
    assert r.status_code == 400


def test_route_accepts_a_manual_zmocnitel(client):
    """Plná moc se občas dělá pro někoho, kdo v historii vůbec není."""
    r = client.post("/api/plna-moc", json={
        "profil": "David", "s_vozidlem": True,
        "rucne": {"jmeno": "NOVÁ FIRMA S.R.O.", "rc_ic": "12345678",
                  "adresa": "HLAVNÍ 1, BRNO", "rz": "5T99999", "vin": "WVWZZZ3CZDE157718"},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["zmocnitel"] == "NOVÁ FIRMA S.R.O."
    assert body["s_vozidlem"] is True
    assert "NOVA-FIRMA" in body["soubor"]


def test_manual_entry_needs_a_name(client):
    """Bez jména není koho zmocnit — nesmí vzniknout prázdná plná moc."""
    r = client.post("/api/plna-moc", json={
        "profil": "David", "rucne": {"jmeno": "", "rc_ic": "1"}})
    assert r.status_code == 400


def test_route_lists_available_zmocnenci(client):
    kdo = {z["profil"] for z in client.get("/api/pm-zmocnenci").get_json()}
    assert {"David", "Petr"} <= kdo


# ── Bez vozidla se ten řádek z papíru odebere úplně ─────────────────────────────
def _pole(pdf_bytes):
    return sorted((pypdf.PdfReader(io.BytesIO(pdf_bytes)).get_fields() or {}).keys())


def test_bez_vozidla_odebere_radky_rz_a_vin(zadost):
    """Nechat kolonky prázdné nestačí — na papíře pak visí dva popisky
    s prázdnými řádky. Vzorem je Petrova šablona, která je nemá vůbec."""
    d, f = zadost
    strana = next(s for s in prefill.strany(d, f)["strany"] if s["role"] == "Nový vlastník")
    path, _ = pm.sablona(A.BASE_DIR, "David")
    plny = A.fill_pdf(path, pm.build_fields(strana, None))
    assert "Text4" in _pole(plny) and "Text5" in _pole(plny), "šablona ta pole má mít"

    orez = pm.bez_vozidla(plny)
    assert _pole(orez) == ["Text1", "Text2", "Text3", "Text8"]
    petr_path, _ = pm.sablona(A.BASE_DIR, "Petr")
    assert _pole(orez) == _pole(A.fill_pdf(petr_path, pm.build_fields(strana, None))),         "má vypadat přesně jako Petrova plná moc"


def test_bez_vozidla_nechava_ostatni_udaje(zadost):
    d, f = zadost
    strana = next(s for s in prefill.strany(d, f)["strany"] if s["role"] == "Nový vlastník")
    path, _ = pm.sablona(A.BASE_DIR, "David")
    orez = pm.bez_vozidla(A.fill_pdf(path, pm.build_fields(strana, None)))
    hodnoty = pypdf.PdfReader(io.BytesIO(orez)).get_fields()
    assert hodnoty["Text1"].get("/V") == "JAN NOVÁK"


def test_bez_vozidla_neublizi_sablone_ktera_ta_pole_nema():
    path, _ = pm.sablona(A.BASE_DIR, "Petr")
    puvodni = A.fill_pdf(path, pm.build_fields({"jmeno": "X", "rc_ic": "1", "adresa": "Y"}))
    assert pm.bez_vozidla(puvodni) == puvodni


def test_route_bez_zaskrtnuti_vyrobi_papir_bez_radku(client, zadost, monkeypatch):
    """To hlavní: zaškrtávátko rozhoduje, jestli tam ty řádky VŮBEC jsou."""
    d, f = zadost
    monkeypatch.setattr(A, "DATA_DIR", d)
    for chce, ocekavane in ((False, ["Text1", "Text2", "Text3", "Text8"]),
                            (True, ["Text1", "Text2", "Text3", "Text4", "Text5", "Text8"])):
        r = client.post("/api/plna-moc", json={
            "zdroj": f, "role": "Nový vlastník", "s_vozidlem": chce, "profil": "David"})
        assert r.status_code == 200 and r.get_json()["success"], r.get_json()
        soubor = r.get_json()["soubor"]
        with open(os.path.join(d, "output", soubor), "rb") as fh:
            assert _pole(fh.read()) == ocekavane, "s_vozidlem=%s" % chce
