"""Postaví šablonu plné moci pro dalšího zmocněnce.

Všechny plné moci jsou TENTÝŽ papír (David, Petr, Roman) — liší se jen jedním
natištěným řádkem se zmocněncem pod „zmocňuji tímto zmocněnce". Úřad tak
dostane stejný tiskopis bez ohledu na to, kdo ho tiskl, a veškerá logika
kolem RZ/VIN v pm.py funguje beze změny.

Skript vezme Petrovu šablonu (bez natištěných kolonek RZ/VIN), smaže jeho
řádek a na přesně stejné místo vysází nový.

Osobní údaje (adresa, datum narození) se předávají JEN jako argument — nesmí
skončit v gitu, repozitář je veřejný. Výstupní PDF je v .gitignore.

Použití:
    python scripts/postav_plnou_moc.py pdfs/plna_moc_jmeno.pdf \\
        "Jana Nováka, Ukázková 1/2, Brno, nar. 01.01.1990"

(Jméno ve 4. pádě, stejně jako „Petra Koska" na Petrově šabloně.)

Písmo: Petrův řádek je nevložená Helvetica (WinAnsi), která neumí „ň" ani
další česká písmena mimo Latin-1. Místo ní se vkládá Arial — má s Helveticou
identické metriky a řádek „ke všem úkonům" hned pod ním je Arialem taky.
"""
from __future__ import annotations

import os
import sys

import fitz  # PyMuPDF

ZAKLAD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "pdfs", "plna_moc_petr.pdf")

# Změřeno v Petrově šabloně (get_text "dict"): Helvetica 11,04 b, účaří
# y=360,52 od horního okraje, začátek x=174,0.
PUVODNI_BBOX = fitz.Rect(172.0, 347.0, 452.0, 365.5)
UCARI = fitz.Point(174.0, 360.52)
VELIKOST = 11.04

ARIAL_KANDIDATI = [
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

POVINNA_POLE = {"Text1", "Text2", "Text3", "Text8"}


def najdi_arial() -> str:
    for cesta in ARIAL_KANDIDATI:
        if os.path.exists(cesta):
            return cesta
    raise SystemExit("Nenašel jsem Arial ani Liberation Sans — bez nich nejde vysázet „ň“.")


def postav(vystup: str, radek: str) -> None:
    doc = fitz.open(ZAKLAD)
    page = doc[0]

    puvodni = page.get_textbox(PUVODNI_BBOX).strip()
    if "Koska" not in puvodni:
        raise SystemExit(f"Čekal jsem Petrův řádek, našel jsem: {puvodni!r}")

    # Jen text — kreslené linky a obrázky pod ním nechat být.
    page.add_redact_annot(PUVODNI_BBOX)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    page.insert_font(fontname="ArialCZ", fontfile=najdi_arial())
    page.insert_text(UCARI, radek, fontname="ArialCZ", fontsize=VELIKOST, color=(0, 0, 0))

    pole = {w.field_name for w in page.widgets()}
    chybi = POVINNA_POLE - pole
    if chybi:
        raise SystemExit(f"Po úpravě zmizela pole formuláře: {sorted(chybi)}")

    doc.save(vystup, garbage=3, deflate=True)
    print(f"hotovo: {vystup}")
    print(f"  natištěno: {page.get_textbox(PUVODNI_BBOX).strip()}")
    print(f"  pole: {sorted(pole)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    postav(sys.argv[1], sys.argv[2])
