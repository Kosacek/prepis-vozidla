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
from pypdf.generic import (ArrayObject, DictionaryObject, FloatObject,
                           NameObject, TextStringObject)
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

# profil v appce -> šablona. „kolonky_v_sablone" říká, jestli tiskopis řádky
# RZ/VIN natištěné MÁ. Petrova verze je nemá — dokreslí se; Davidova je má —
# když se vozidlo neuvádí, odeberou se. Na výsledku to není poznat.
ZMOCNENCI: dict[str, dict] = {
    "David": {"soubor": "plna_moc_david.pdf", "kdo": "David Kosek",
              "kolonky_v_sablone": True},
    "Petr": {"soubor": "plna_moc_petr.pdf", "kdo": "Petr Kosek",
             "kolonky_v_sablone": False},
    # Roman zatím vlastní šablonu nemá — David ji dodá. Do té doby si musí
    # vybrat, na koho plnou moc vystavit; radši to přiznat než mlčky použít
    # cizí jméno na dokumentu, který jde na úřad.
}


def dostupni() -> list[dict]:
    """Zmocněnci, na které umíme plnou moc vystavit — pro nabídku v UI.

    ``ma_vozidlo`` je dnes u všech True: kolonky na RZ a VIN se podle potřeby
    dokreslí i do šablony, která je natištěné nemá.
    """
    return [{"profil": k, "kdo": v["kdo"], "ma_vozidlo": True}
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

# Opačný směr: Petrova šablona ten řádek natištěný NEMÁ, takže se do ní dokreslí.
# Rozměry i vzhled se berou z Davidovy šablony, aby to byl tentýž papír — obě
# mají Text1/2/3/8 na stejných souřadnicích i se stejným rámečkem, takže stačí
# naklonovat existující kolonku a posadit ji o řádek níž.
#          pole,    popisek, rect kolonky (změřeno v Davidově šabloně)
VOZIDLO_RADKY = (
    ("Text4", "RZ:", (181.2, 642.4, 467.2, 662.4)),
    ("Text5", "VIN:", (181.2, 612.4, 466.7, 632.4)),
)
POPISEK_X = 71.0          # levý okraj popisků „Zmocnitel:", „Adresa:", …
POPISEK_FONT = ("Helvetica-Bold", 11)
# Účaří popisku nad spodní hranou kolonky. Doměřeno proti Davidově šabloně:
# popisek „VIN:" tam končí na 226,9 od horního okraje a s touhle hodnotou
# sedí Petrův na 226,90 — rozdíl 0,01 bodu, tedy setina milimetru.
POPISEK_NAD_HRANOU = 6.6
VZOR_POLE = "Text3"       # ze které kolonky se opisuje vzhled


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


def _popisky_vrstva(sirka: float, vyska: float):
    """Natištěné „RZ:" a „VIN:" — v šabloně, která je nemá."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(sirka, vyska))
    c.setFont(*POPISEK_FONT)
    c.setFillColorRGB(0, 0, 0)
    for _, popisek, rect in VOZIDLO_RADKY:
        c.drawString(POPISEK_X, rect[1] + POPISEK_NAD_HRANOU, popisek)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def s_vozidlem(pdf_bytes: bytes, vozidlo: dict) -> bytes:
    """Doplní do plné moci řádky RZ a VIN i tam, kde je šablona natištěné nemá.

    Šablony, které je mají (Davidova), projdou beze změny — vyplnily se rovnou.
    """
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    page = writer.pages[0]
    anotace = list(page.get("/Annots") or [])
    podle_jmena = {str(a.get_object().get("/T") or ""): a.get_object() for a in anotace}
    if all(k in podle_jmena for k in VOZIDLO_POLE):
        return pdf_bytes

    vzor = podle_jmena.get(VZOR_POLE)
    if vzor is None:                       # šablona bez kolonek — nemá se z čeho opsat
        return pdf_bytes

    hodnoty = {"Text4": vozidlo.get("rz", ""), "Text5": vozidlo.get("vin", "")}
    for jmeno, _, rect in VOZIDLO_RADKY:
        if jmeno in podle_jmena:
            continue
        nove = DictionaryObject()
        # Vzhled (rámeček, pozadí, písmo) se opisuje z existující kolonky, ať je
        # to na papíře k nerozeznání od ostatních řádků.
        for klic in ("/Type", "/Subtype", "/FT", "/F", "/DA", "/MK", "/BS", "/P", "/Ff"):
            if klic in vzor:
                nove[NameObject(klic)] = vzor.raw_get(klic)
        nove[NameObject("/Rect")] = ArrayObject([FloatObject(x) for x in rect])
        nove[NameObject("/T")] = TextStringObject(jmeno)
        nove[NameObject("/V")] = TextStringObject(str(hodnoty[jmeno] or "").upper())
        odkaz = writer._add_object(nove)
        anotace.append(odkaz)
        akro = writer._root_object.get("/AcroForm")
        akro = akro.get_object() if akro is not None else None
        if akro is not None and "/Fields" in akro:
            akro[NameObject("/Fields")].append(odkaz)

    page[NameObject("/Annots")] = ArrayObject(anotace)
    page.merge_page(_popisky_vrstva(float(page.mediabox.width),
                                    float(page.mediabox.height)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
