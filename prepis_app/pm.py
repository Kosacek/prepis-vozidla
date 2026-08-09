"""Plná moc k zastupování na registru vozidel.

Vyplňuje se Davidova/Petrova hotová šablona, negeneruje se nový dokument —
tenhle papír chodí na úřad a má vypadat přesně jako ten, který tam berou roky.

Zmocněnec je v šabloně **natištěný napevno** (jméno, datum narození, adresa),
proto je pro každého vlastní soubor. Kdo to bude, se bere z profilu v hlavičce
appky (👤), takže se nikde nevybírá znovu.

Pole tiskopisu (změřeno proti popiskům):
    Text1  Zmocnitel          Text4  RZ    (jen šablona s vozidlem)
    Text2  RČ/IČ              Text5  VIN   (jen šablona s vozidlem)
    Text3  Adresa             Text8  V Brně dne

Datum je **dnešní**, ne zítřejší jako na žádostech: žádosti se post-datují na
nejbližší pracovní den, ale plná moc se podepisuje ten den, kdy ji vyplňuješ.
"""
from __future__ import annotations

import os
from datetime import datetime

POLE = {
    "zmocnitel": "Text1",
    "rc_ic": "Text2",
    "adresa": "Text3",
    "rz": "Text4",
    "vin": "Text5",
    "datum": "Text8",
}

# profil v appce -> šablona. „ma_vozidlo" říká, jestli tiskopis vůbec má
# kolonky RZ/VIN — Petrova verze je nemá, takže na ní vozidlo uvést nejde.
ZMOCNENCI: dict[str, dict] = {
    "David": {"soubor": "plna_moc_david.pdf", "kdo": "David Kosek", "ma_vozidlo": True},
    "Petr": {"soubor": "plna_moc_petr.pdf", "kdo": "Petr Kosek", "ma_vozidlo": False},
    # Roman zatím vlastní šablonu nemá — David ji dodá. Do té doby si musí
    # vybrat, na koho plnou moc vystavit; radši to přiznat než mlčky použít
    # cizí jméno na dokumentu, který jde na úřad.
}


def dostupni() -> list[dict]:
    """Zmocněnci, na které umíme plnou moc vystavit — pro nabídku v UI."""
    return [{"profil": k, "kdo": v["kdo"], "ma_vozidlo": v["ma_vozidlo"]}
            for k, v in ZMOCNENCI.items()]


def sablona(base_dir: str, profil: str) -> tuple[str, dict] | None:
    """Cesta k šabloně pro daný profil, nebo None když ji pro něj nemáme."""
    z = ZMOCNENCI.get((profil or "").strip())
    if not z:
        return None
    path = os.path.join(base_dir, "pdfs", z["soubor"])
    return (path, z) if os.path.exists(path) else None


def build_fields(strana: dict, vozidlo: dict | None = None,
                 dnes: str | None = None) -> dict:
    """Data do šablony. ``strana`` je jedna položka z ``prefill.strany``.

    ``vozidlo`` se předá jen když ho uživatel chce v plné moci mít — a i tak
    se propíše jen do šablony, která na něj kolonky má.
    """
    voz = vozidlo or {}
    return {
        POLE["zmocnitel"]: strana.get("jmeno", ""),
        POLE["rc_ic"]: strana.get("rc_ic", ""),
        POLE["adresa"]: strana.get("adresa", ""),
        POLE["rz"]: voz.get("rz", ""),
        POLE["vin"]: voz.get("vin", ""),
        POLE["datum"]: dnes or datetime.now().strftime("%d.%m.%Y"),
    }
