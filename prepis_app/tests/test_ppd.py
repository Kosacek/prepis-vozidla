"""Unit tests for the PPD (cash-receipt) module."""
import io
import os

import pytest
from pypdf import PdfReader

import ppd


# ── amount in words ─────────────────────────────────────────────────────────
def test_words_declension():
    assert "korun" in ppd.amount_to_words_cs(1300)      # 5+/hundreds → korun
    assert "tisíc" in ppd.amount_to_words_cs(1300)
    assert "koruna" in ppd.amount_to_words_cs(1)         # 1 → koruna
    assert "koruny" in ppd.amount_to_words_cs(22)        # 2-4 → koruny
    assert "korun" in ppd.amount_to_words_cs(5)          # 5 → korun
    # no heller tail leaks through
    assert "hal" not in ppd.amount_to_words_cs(1300)


# ── numbering + ledger ──────────────────────────────────────────────────────
def test_numbering_increments_and_persists(tmp_path):
    d = str(tmp_path)
    rec = {"date": "02.06.2026", "payer": "X", "amount": 1300, "purpose": "p", "vehicle": "1AB2345"}
    assert ppd.reserve_ppd_number_and_log(d, rec) == 1
    assert ppd.reserve_ppd_number_and_log(d, rec) == 2
    assert ppd.reserve_ppd_number_and_log(d, rec) == 3
    # evidence file exists and has 3 data rows + header
    path = ppd._evidence_path(d)
    assert os.path.exists(path)
    import openpyxl
    ws = openpyxl.load_workbook(path).active
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] is not None]
    assert len(rows) == 3
    assert [r[0] for r in rows] == [1, 2, 3]


def test_numbering_derives_from_ledger_max(tmp_path):
    d = str(tmp_path)
    rec = {"date": "x", "payer": "X", "amount": 800, "purpose": "p", "vehicle": ""}
    ppd.reserve_ppd_number_and_log(d, rec)   # 1
    ppd.reserve_ppd_number_and_log(d, rec)   # 2
    # A fresh call re-derives max from the file → 3 (no separate counter to desync)
    assert ppd.reserve_ppd_number_and_log(d, rec) == 3


# ── PDF render ──────────────────────────────────────────────────────────────
def test_pdf_renders_with_czech_text():
    pdf = ppd.build_ppd_pdf({
        "number": 7,
        "date": "02.06.2026",
        "payer": "PETR KUPUJÍCÍ",
        "amount": 1300,
        "purpose": "Za vyřízení přepisu vozidla RZ 1AB2345",
    })
    assert pdf[:4] == b"%PDF"
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "PŘÍJMOVÝ POKLADNÍ DOKLAD" in text
    assert "7" in text
    assert "PETR KUPUJÍCÍ" in text
    assert "1300" in text
    assert "korun" in text          # amount-in-words rendered (TTF works)
    assert "07133880" in text       # issuer IČO
