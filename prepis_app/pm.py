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

import io
import os
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject
from reportlab.lib.colors import white
from reportlab.pdfgen import canvas

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


# ── Plná moc bez vozidla ─────────────────────────────────────────────────────
# Kolonky RZ a VIN jsou v Davidově šabloně natištěné napevno. Nechat je prázdné
# nestačí — na papíře pak visí dva popisky s prázdnými řádky, což nikdo nechtěl.
# Petrova šablona je nemá vůbec a přesně tak má vypadat i Davidova, když se
# vozidlo neuvádí: pruh se překryje a pole se z formuláře odstraní, aby do nich
# nešlo ani omylem psát.
#
# Souřadnice jsou v bodech od SPODNÍHO okraje (tak je počítá PDF).
# Změřeno v šabloně: popisek „RZ:" leží na 645–658, „VIN:" na 615–631,
# pole Text4 642,4–662,4 a Text5 612,4–632,4 — pruh je bere všechny s rezervou.
VOZIDLO_POLE = ("Text4", "Text5")
VOZIDLO_PRUH = (58.0, 608.0, 485.0, 667.0)   # x0, y0, x1, y1


def _prekryv(sirka: float, vyska: float):
    """Bílý obdélník přes pruh s RZ/VIN — jinak by popisky zůstaly vidět."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(sirka, vyska))
    x0, y0, x1, y1 = VOZIDLO_PRUH
    c.setFillColor(white)
    c.setStrokeColor(white)
    c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=1)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def bez_vozidla(pdf_bytes: bytes) -> bytes:
    """Vrátí tutéž plnou moc, ale bez řádků na RZ a VIN.

    Šablony bez těch kolonek (Petrova) projdou beze změny — není co odebírat.
    """
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    page = writer.pages[0]

    puvodni = list(page.get("/Annots") or [])
    zbyle = [a for a in puvodni
             if str(a.get_object().get("/T") or "") not in VOZIDLO_POLE]
    if len(zbyle) == len(puvodni):
        return pdf_bytes                      # šablona ta pole nemá

    page[NameObject("/Annots")] = ArrayObject(zbyle)
    # Stránka už patří writeru, jinak pypdf slučování považuje za nespolehlivé.
    page.merge_page(_prekryv(float(page.mediabox.width), float(page.mediabox.height)))

    # Odebrat je i z /AcroForm, jinak je čtečka pořád nabízí k vyplnění.
    akro = writer._root_object.get("/AcroForm")
    akro = akro.get_object() if akro is not None else None
    if akro is not None and "/Fields" in akro:
        akro[NameObject("/Fields")] = ArrayObject(
            [f for f in akro["/Fields"]
             if str(f.get_object().get("/T") or "") not in VOZIDLO_POLE])

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
