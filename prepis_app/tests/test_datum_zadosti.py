"""Datum na tiskopisu: DNEŠEK, když se to na přepážku ještě stihne — jinak
další pracovní den.

Reálná stížnost: appka dřív dávala VŽDYCKY zítřek, i ráno den před tím, co se
na Magistrát skutečně jde. Přepážka registru vozidel má ale kratší úřední
hodiny než celý úřad — David je zná z první ruky:
    pondělí, středa   — do 17:00
    úterý, čtvrtek, pátek — jen do 12:00 (odpoledne zavřeno)
    sobota, neděle    — zavřeno celý den

Testovací data: 14.–20. 9. 2026 je po/út/st/čt/pá/so/ne (ověřeno přes
datetime.date(...).strftime('%A'), ne odhadem).
"""
from datetime import datetime

import app as A


def _dt(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute)


# ── pondělí a středa: přepážka do 17:00 ──────────────────────────────────────
def test_pondeli_pred_17_je_dnes():
    assert _dt(14, 8).weekday() == 0   # pondělí — self-check
    assert A._next_working_day(_dt(14, 8, 0)) == "14.09.2026"
    assert A._next_working_day(_dt(14, 16, 59)) == "14.09.2026"


def test_pondeli_v_17_a_pozdeji_je_uterek():
    assert A._next_working_day(_dt(14, 17, 0)) == "15.09.2026"
    assert A._next_working_day(_dt(14, 22, 0)) == "15.09.2026"


def test_streda_pred_17_je_dnes():
    assert _dt(16, 8).weekday() == 2   # středa — self-check
    assert A._next_working_day(_dt(16, 9, 0)) == "16.09.2026"


def test_streda_po_17_je_ctvrtek():
    assert A._next_working_day(_dt(16, 17, 30)) == "17.09.2026"


# ── úterý, čtvrtek, pátek: jen do 12:00 ─────────────────────────────────────
def test_uteri_pred_polednem_je_dnes():
    assert _dt(15, 8).weekday() == 1   # úterý — self-check
    assert A._next_working_day(_dt(15, 11, 59)) == "15.09.2026"


def test_uteri_v_poledne_a_pozdeji_je_streda():
    assert A._next_working_day(_dt(15, 12, 0)) == "16.09.2026"
    assert A._next_working_day(_dt(15, 16, 0)) == "16.09.2026"


def test_ctvrtek_pred_polednem_je_dnes():
    assert _dt(17, 8).weekday() == 3   # čtvrtek — self-check
    assert A._next_working_day(_dt(17, 11, 0)) == "17.09.2026"


def test_ctvrtek_po_poledni_je_patek():
    assert A._next_working_day(_dt(17, 13, 0)) == "18.09.2026"


def test_patek_pred_polednem_je_dnes():
    assert _dt(18, 8).weekday() == 4   # pátek — self-check
    assert A._next_working_day(_dt(18, 9, 0)) == "18.09.2026"


def test_patek_po_poledni_preskoci_vikend_na_pondeli():
    assert A._next_working_day(_dt(18, 15, 0)) == "21.09.2026"


# ── víkend: zavřeno celý den, žádost jde na pondělí ──────────────────────────
def test_sobota_kdykoliv_je_pondeli():
    assert _dt(19, 8).weekday() == 5   # sobota — self-check
    assert A._next_working_day(_dt(19, 7, 0)) == "21.09.2026"
    assert A._next_working_day(_dt(19, 20, 0)) == "21.09.2026"


def test_nedele_kdykoliv_je_pondeli():
    assert _dt(20, 8).weekday() == 6   # neděle — self-check
    assert A._next_working_day(_dt(20, 10, 0)) == "21.09.2026"


# ── beze zadaného času se použije skutečné "teď" ────────────────────────────
def test_bez_argumentu_pouzije_realne_ted():
    assert A._next_working_day() == A._next_working_day(datetime.now())
