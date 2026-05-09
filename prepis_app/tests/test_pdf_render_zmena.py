"""Render zmena_udaju.pdf with a known field map and verify /V annotations match."""
import io
from pypdf import PdfReader
from app import fill_pdf, build_zmena_fields, PDF_ZMENA


def test_render_round_trip():
    data = {
        "novy_jmeno": "TESTOVACI VLASTNIK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_ico": "",
        "novy_adresa": "TESTOVACI ADRESA 1",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    fields = build_zmena_fields(data)
    pdf_bytes = fill_pdf(PDF_ZMENA, fields)
    assert len(pdf_bytes) > 1000  # sanity

    reader = PdfReader(io.BytesIO(pdf_bytes))
    rendered = reader.get_fields() or {}

    def v(name):
        return str(rendered[name].get("/V") or "")

    # fill_pdf uppercases all text fields EXCEPT NO_UPPER = {V, V_2, V_3, V_4, dne, dne_2, dne_3, dne_4}.
    # So zadost_zmena (→ fill_12) IS uppercased; V is NOT.
    assert "1AB2345" in v("comb_1")
    assert "WBA3A5C51DF123456" in v("comb_2")
    assert "TESTOVACI VLASTNIK" in v("fill_2")
    assert "850101/1234" in v("comb_3")
    assert v("fill_7") == ""    # provozovatel jméno blank
    assert v("fill_11") == ""   # provozovatel PSČ blank
    assert "ZÁPIS A50-X" in v("fill_12")
    assert v("V") == "Brně"     # NOT uppercased
