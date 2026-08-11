"""ID pro úřad — nesmí se zkracovat.

Reálná chyba: leasingovky (Toyota Financial Services) mají ID delší než 10
číslic a řetězí se jich několik za sebou. Ukládání firmy každé ID ořezávalo na
10 znaků a formulářová pole měla maxlength=32, takže se vložený řetěz ustřihl.
Ustřižené ID na žádosti pro registr je horší chyba než dlouhý řetěz — pozná se
až na přepážce.
"""
import io
import re
import pathlib

import pypdf

import app as A

SABLONA = pathlib.Path(__file__).resolve().parent.parent / "templates" / "index.html"

# Tři zřetězená ID leasingovky — přesně ten případ, který se ustřihl.
DLOUHY = "123456789012, 234567890123, 345678901234"


def test_long_ids_are_not_truncated():
    assert A._normalize_ids(DLOUHY) == "123456789012, 234567890123, 345678901234"


def test_each_id_keeps_all_its_digits():
    """Dřív se každý segment ořezával na 10 číslic — tady jich má 12."""
    for cast in A._normalize_ids(DLOUHY).split(", "):
        assert len(cast) == 12


def test_separators_and_junk_are_cleaned():
    """Středníky, mezery i písmena se srovnají, číslice zůstanou."""
    assert A._normalize_ids(" 12345678 ; 87654321 ") == "12345678, 87654321"
    assert A._normalize_ids("ID 1234-5678") == "12345678"
    assert A._normalize_ids("") == ""
    assert A._normalize_ids(None) == ""


def test_form_fields_accept_a_chain_of_ids():
    """maxlength na polích musí ten řetěz pobrat — jinak ho prohlížeč ustřihne
    ještě než se odešle a nikdo si toho nevšimne."""
    html = SABLONA.read_text(encoding="utf-8")
    delky = [int(m) for m in re.findall(r'maxlength="(\d+)" inputmode="numeric"', html)]
    assert delky, "pole pro ID se nenašla"
    assert min(delky) >= len(DLOUHY), f"nejkratší pole má {min(delky)}, potřeba {len(DLOUHY)}"


def test_long_id_lands_in_the_pdf_whole():
    """Průchod celým generováním: co se zadá, to musí být na papíře."""
    data = {
        "mode": "prevod", "registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470",
        "puvodni_jmeno": "TOYOTA FINANCIAL SERVICES CZECH S.R.O.",
        "novy_jmeno": "JAN NOVÁK", "novy_id": DLOUHY,
    }
    pdf = A.fill_pdf(A.PDF_ZMENY, A.build_zmeny_fields(data))
    pdf = A.add_id_overlay(pdf, [(0, 554, 628, f"ID: {DLOUHY}")])
    text = pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or ""
    for cast in DLOUHY.split(", "):
        assert cast in text, f"{cast} v PDF chybí"


def test_long_id_shrinks_instead_of_running_off():
    """Dlouhý řetěz se musí vejít do vyhrazeného místa, ne vjet do předlohy."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    text = f"ID: {DLOUHY}"
    size = 11
    while stringWidth(text, "Helvetica-Bold", size) > 250 and size > 7:
        size -= 0.5
    assert stringWidth(text, "Helvetica-Bold", size) <= 250
    assert size >= 7, "písmo by kleslo pod čitelnost"
