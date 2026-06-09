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


def test_read_ppd_log(tmp_path):
    d = str(tmp_path)
    assert ppd.read_ppd_log(d) == []   # empty before any receipt
    ppd.reserve_ppd_number_and_log(d, {"date": "01.06.2026", "payer": "A", "amount": 1300, "purpose": "p", "vehicle": "1AB2345"})
    ppd.reserve_ppd_number_and_log(d, {"date": "02.06.2026", "payer": "B s.r.o.", "amount": 800, "purpose": "p", "vehicle": "2CD"})
    log = ppd.read_ppd_log(d)
    assert [r["cislo"] for r in log] == [2, 1]          # newest first
    assert log[0]["prijato_od"] == "B s.r.o."
    assert log[1]["castka"] == 1300


def test_delete_ppd(tmp_path):
    d = str(tmp_path)
    ppd.reserve_ppd_number_and_log(d, {"date": "x", "payer": "A", "amount": 1300, "purpose": "p", "vehicle": ""})  # 1
    ppd.reserve_ppd_number_and_log(d, {"date": "x", "payer": "B", "amount": 800, "purpose": "p", "vehicle": ""})   # 2
    assert ppd.delete_ppd(d, 1) is True
    assert [r["cislo"] for r in ppd.read_ppd_log(d)] == [2]
    assert ppd.delete_ppd(d, 99) is False                      # non-existent → no-op
    # numbers are never reused — next allocation is max(remaining)+1 = 3, not 1
    assert ppd.reserve_ppd_number_and_log(d, {"date": "x", "payer": "C", "amount": 1, "purpose": "p", "vehicle": ""}) == 3


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
        "payer": "AUTO CARDION s.r.o.",
        "payer_ico": "04156854",
        "amount": 1300,
        "purpose": "Zastupování na MMB",
    })
    assert pdf[:4] == b"%PDF"
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "PŘÍJMOVÝ POKLADNÍ DOKLAD" in text
    assert "7" in text
    assert "AUTO CARDION s.r.o." in text
    assert "04156854" in text       # payer IČO rendered
    assert "1300" in text
    assert "korun" in text          # amount-in-words rendered (TTF works)
    assert "07133880" in text       # issuer IČO


def test_pdf_renders_address_and_spz():
    pdf = ppd.build_ppd_pdf({
        "number": 9, "date": "02.06.2026",
        "payer": "AUTO CARDION s.r.o.", "payer_ico": "04156854",
        "payer_address": "Hlavní 456, 60200 Brno",
        "spz": "1AB2345", "vin": "TMBxyz123",
        "amount": 1300, "purpose": "Zastupování na MMB",
    })
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "Hlavní 456, 60200 Brno" in text   # payer address rendered
    assert "1AB2345" in text                   # SPZ rendered
    assert "TMBxyz123" not in text             # VIN suppressed when SPZ present


def test_pdf_vin_fallback_when_no_spz():
    pdf = ppd.build_ppd_pdf({
        "number": 10, "date": "02.06.2026", "payer": "Jan Novák",
        "spz": "", "vin": "TMBVIN0001",
        "amount": 800, "purpose": "Zastupování na MMB",
    })
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "TMBVIN0001" in text                # VIN shown when there's no plate


# ── append-only backup + restore ────────────────────────────────────────────
def _issue(d, payer="A s.r.o.", amount=1300):
    """Mimic app.py: reserve a live ledger number, then mirror it to the
    append-only backup. Returns the allocated číslo."""
    n = ppd.reserve_ppd_number_and_log(d, {"date": "02.06.2026", "payer": payer,
        "amount": amount, "purpose": "Zastupování na MMB", "vehicle": "1AB2345"})
    ppd.append_backup(d, {"cislo": n, "ts": "2026-06-02T10:00:00",
        "date": "02.06.2026", "payer": payer, "payer_ico": "04156854",
        "payer_address": "Hlavní 5, 60200 Brno", "amount": amount,
        "purpose": "Zastupování na MMB", "spz": "1AB2345", "vin": ""})
    return n


def test_backup_append_and_read(tmp_path):
    d = str(tmp_path)
    assert ppd.read_backup(d) == []
    _issue(d, payer="A s.r.o.")
    _issue(d, payer="B s.r.o.")
    b = ppd.read_backup(d)
    assert [r["cislo"] for r in b] == [2, 1]              # newest first
    assert b[0]["prijato_od"] == "B s.r.o."
    assert b[1]["adresa"] == "Hlavní 5, 60200 Brno"
    assert b[1]["spz"] == "1AB2345"


def test_backup_survives_delete_and_lists_deleted(tmp_path):
    d = str(tmp_path)
    _issue(d); _issue(d)                                  # 1, 2
    assert ppd.delete_ppd(d, 1) is True
    assert [r["cislo"] for r in ppd.read_ppd_log(d)] == [2]    # gone from live
    assert 1 in {r["cislo"] for r in ppd.read_backup(d)}       # kept in backup
    assert [r["cislo"] for r in ppd.deleted_ppd(d)] == [1]     # surfaced as deleted


def test_restore_puts_it_back(tmp_path):
    d = str(tmp_path)
    _issue(d); _issue(d)                                  # 1, 2
    ppd.delete_ppd(d, 1)
    rec = next(r for r in ppd.read_backup(d) if r["cislo"] == 1)
    ok = ppd.restore_ppd_row(d, {"cislo": 1, "datum": rec["datum"],
        "prijato_od": rec["prijato_od"], "castka": rec["castka"],
        "ucel": rec["ucel"], "vozidlo": rec["spz"] or rec["vin"]})
    assert ok is True
    assert 1 in {r["cislo"] for r in ppd.read_ppd_log(d)}      # back in live
    assert ppd.deleted_ppd(d) == []                            # nothing deleted now


def test_restore_noop_when_already_live(tmp_path):
    d = str(tmp_path)
    _issue(d)                                             # 1 (live)
    assert ppd.restore_ppd_row(d, {"cislo": 1, "datum": "x", "prijato_od": "A",
        "castka": 1300, "ucel": "p", "vozidlo": "1AB2345"}) is False


def test_numbering_never_reuses_after_deleting_top(tmp_path):
    # Deleting the highest receipt must NOT let the next issue reuse its number,
    # because the backup keeps that number as the high-water mark.
    d = str(tmp_path)
    _issue(d); _issue(d)                                  # 1, 2
    ppd.delete_ppd(d, 2)                                  # live max drops to 1
    assert _issue(d) == 3                                 # not 2 again
