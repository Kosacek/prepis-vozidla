"""Přečte dřív vygenerovanou žádost zpátky do dat formuláře.

Proč z PDF a ne z nějakého indexu: hotové žádosti v ``DATA_DIR/output`` už
obsahují úplně všechno — jméno, adresu, PSČ, IČO i rodné číslo. Kdybychom si
tytéž údaje ukládali ještě jednou do vlastního souboru, vznikne druhá kopie
osobních dat (včetně RČ), kterou je potřeba hlídat a zálohovat. Takhle
nevzniká žádné nové úložiště a funguje to i pro všech ~850 starých žádostí.

Používá se pro „Ostatní úkony" (3RZ): vybereš auto, které jsi nedávno
přepisoval, a vlastník i vozidlo se doplní samy.

Mapy jsou inverzí ``build_*_fields`` v app.py — když se změní tam, musí se
změnit i tady (drží to test_prefill.py).
"""
from __future__ import annotations

import os
from pypdf import PdfReader

import hledani

# pdf pole -> klíč dat formuláře. Bereme vždy NOVÉHO vlastníka: navazující
# úkon (třetí značka) se dělá na toho, kdo auto právě dostal, ne na prodejce.
_MAPS: dict[str, dict[str, str]] = {
    "zmeny": {
        "comb_1": "registracni_znacka", "comb_2": "vin", "Druh vozidla": "druh_vozidla",
        "fill_8": "novy_jmeno", "comb_5_2": "novy_rc_1", "undefined_4": "novy_rc_2",
        "comb_7": "novy_ico", "osoby 1_3": "novy_adresa", "fill_11": "novy_psc",
        "fill_12": "novy_prov_jmeno", "comb_2_2": "novy_prov_rc_1",
        "undefined_3": "novy_prov_rc_2", "comb_4": "novy_prov_ico",
        "osoby 1_4": "novy_prov_adresa",
    },
    "zapis": {
        "comb_1_2": "vin", "Text6": "druh_vozidla", "Text12": "kategorie_vozidla",
        "Text7": "typ_vozidla", "Text8": "znacka",
        "Text3": "novy_jmeno", "comb_3": "novy_rc_1", "undefined": "novy_rc_2",
        "comb_5": "novy_ico", "osoby": "novy_adresa", "fill_2": "novy_psc",
        "fill_3": "novy_prov_jmeno", "comb_6": "novy_prov_rc_1",
        "undefined_2": "novy_prov_rc_2", "comb_8": "novy_prov_ico",
        "fill_7": "novy_prov_adresa", "fill_5": "novy_prov_psc",
    },
    "zmena": {
        "comb_1": "registracni_znacka", "comb_2": "vin", "Druh vozidla": "druh_vozidla",
        "fill_2": "novy_jmeno", "comb_3": "_novy_rc", "comb_4": "novy_ico",
        "fill_6": "novy_psc",
        "fill_7": "novy_prov_jmeno", "comb_5": "_novy_prov_rc",
        "comb_6": "novy_prov_ico", "fill_11": "novy_prov_psc",
    },
    "3rz": {
        "RZ": "registracni_znacka", "VIN": "vin", "Druh vozidla": "druh_vozidla",
        "fill_2": "novy_jmeno", "comb_5": "novy_rc_1", "comb_6": "novy_rc_2",
        "comb_4": "novy_ico", "osoby": "novy_adresa", "fill_5": "novy_psc",
        "fill_6": "novy_prov_jmeno", "comb_1": "novy_prov_rc_1",
        "undefined": "novy_prov_rc_2", "comb_3": "novy_prov_ico",
        "osoby_2": "novy_prov_adresa", "fill_9": "novy_prov_psc",
    },
}

# zmena_udaju.pdf má rodné číslo v JEDNOM poli i s lomítkem, ostatní tiskopisy
# ve dvou — proto se u něj rozděluje zpátky.
_SPLIT = {"_novy_rc": ("novy_rc_1", "novy_rc_2"),
          "_novy_prov_rc": ("novy_prov_rc_1", "novy_prov_rc_2")}


# Adresa vlastníka je u zmena_udaju.pdf pod dlouhým názvem z tiskopisu.
_ZMENA_ADDR = ("Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby "
               " místo podnikání fyzické osoby 1")
_ZMENA_ADDR_P = ("Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby "
                 " místo podnikání fyzické osoby 1_2")
_MAPS["zmena"][_ZMENA_ADDR] = "novy_adresa"
_MAPS["zmena"][_ZMENA_ADDR_P] = "novy_prov_adresa"


def typ_souboru(filename: str) -> str | None:
    """Typ tiskopisu z názvu. Rozbor názvu je jeden pro celou appku (hledani.py),
    aby starý i nový tvar názvu chápalo všechno stejně."""
    rozbor = hledani.rozbor_nazvu(filename)
    return rozbor[0] if rozbor else None


def z_pdf(data_dir: str, filename: str) -> dict:
    """Vrátí data formuláře z dané vygenerované žádosti.

    Prázdný dict, když soubor neexistuje nebo nejde přečíst — předvyplnění je
    pohodlí, nikdy nesmí shodit vyplňování.
    """
    safe = os.path.basename(filename or "")
    kind = typ_souboru(safe)
    if not kind:
        return {}
    path = os.path.join(data_dir, "output", safe)
    if not os.path.exists(path):
        return {}
    try:
        fields = PdfReader(path).get_fields() or {}
    except Exception:
        return {}

    out: dict[str, str] = {}
    for pdf_key, data_key in _MAPS[kind].items():
        raw = fields.get(pdf_key)
        val = str((raw or {}).get("/V") or "").strip()
        if not val:
            continue
        if data_key in _SPLIT:
            a, b = _SPLIT[data_key]
            first, _, second = val.partition("/")
            if first.strip():
                out[a] = first.strip()
            if second.strip():
                out[b] = second.strip()
        else:
            out[data_key] = val

    # Provozovatel se vyplňuje jen když je odlišný — zaškrtnutí odvodíme z toho,
    # jestli v tiskopisu vůbec něco má.
    out["novy_prov_jiny"] = bool(out.get("novy_prov_jmeno"))
    out["_zdroj"] = safe
    out["_typ"] = kind
    return out
