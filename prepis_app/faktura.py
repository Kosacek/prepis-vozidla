"""Faktura (invoice, bank transfer) — own number series + storage + settings.

Numbers are YYYYNNNN (e.g. 20260001): numeric, <= 10 digits, so the number is
the variable symbol. Separate from the PPD series. Mirrors ppd.py: one lock
covers allocation + ledger row + append-only backup row, and the high-water
mark is taken over ledger AND backup so a number is never reused.
PDF drawing lives in faktura_pdf.py, the QR string in spayd.py.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import openpyxl

import spayd
from ppd import ISSUER_ICO, ISSUER_NAME, _HAVE_FCNTL, _atomic_save

if _HAVE_FCNTL:
    import fcntl

DRUH = "faktura"
EVIDENCE_NAME = "faktura_evidence.xlsx"
BACKUP_NAME = "faktura_backup.xlsx"
_LOCK_NAME = "faktura.lock"
DEFAULT_SPLATNOST_DNI = 7
PLACEHOLDER = "[doplnit]"

_HEADER = ["Číslo", "Datum", "Splatnost", "Odběratel", "Částka (Kč)", "Účel", "Vozidlo"]
_BACKUP_HEADER = ["Číslo", "Vystaveno", "Datum", "Splatnost", "Odběratel", "IČO",
                  "Adresa", "Částka (Kč)", "Účel", "Vozidla"]

# Public registry data (ARES), overridable by env ISSUER_ADRESA / ISSUER_SPISOVA_ZNACKA.
DEFAULT_ISSUER_ADRESA = "Cacovická 1592/30a, Husovice, 614 00 Brno"
DEFAULT_ISSUER_SPISOVA_ZNACKA = "C 106352 vedená u Krajského soudu v Brně"


def settings() -> dict:
    """Issuer/payment settings from the environment (read per call)."""
    try:
        dni = int(os.environ.get("FAKTURA_SPLATNOST_DNI", DEFAULT_SPLATNOST_DNI))
    except ValueError:
        dni = DEFAULT_SPLATNOST_DNI
    return {
        "name": ISSUER_NAME,
        "ico": ISSUER_ICO,
        "adresa": os.environ.get("ISSUER_ADRESA", "").strip() or DEFAULT_ISSUER_ADRESA,
        "spisova_znacka": (os.environ.get("ISSUER_SPISOVA_ZNACKA", "").strip()
                           or DEFAULT_ISSUER_SPISOVA_ZNACKA),
        "iban": os.environ.get("FAKTURA_IBAN", "").strip(),
        "ucet": os.environ.get("FAKTURA_UCET", "").strip(),
        "splatnost_dni": max(0, dni),
    }


def dostupna() -> bool:
    """Faktura se smí vystavit jen s platným FAKTURA_IBAN (bez něj by neměla QR Platbu)."""
    try:
        spayd.normalize_iban(settings()["iban"])
    except ValueError:
        return False
    return True


def moznosti() -> dict:
    """Co umí tahle instance vystavit — odpověď GET /api/ppd/moznosti."""
    return {"faktura": dostupna(), "splatnost_dni": settings()["splatnost_dni"]}


def pdf_path(data_dir: str, number: int) -> str:
    return os.path.join(data_dir, "output", f"faktura_{number}.pdf")


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def due_date(issued: date, days: int | None = None) -> date:
    return issued + timedelta(days=settings()["splatnost_dni"] if days is None else days)


def number_prefix(year: int) -> int:
    return year * 10000


def _in_year(value, year: int) -> int:
    """The value as int when it belongs to `year`'s series, else 0."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return v if number_prefix(year) < v <= number_prefix(year) + 9999 else 0


def _max_in_year(ws, year: int) -> int:
    return max([_in_year(r[0], year) for r in ws.iter_rows(min_row=2, values_only=True) if r] or [0])


def _open(path: str, title: str, header: list):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        wb = openpyxl.load_workbook(path)
        return wb, wb.active
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    return wb, ws


def issue_faktura(data_dir: str, rec: dict, today: date | None = None) -> int:
    """Allocate the next number of the current year and write ledger + backup
    rows under one exclusive lock. Returns the number.

    rec: {payer, payer_ico, payer_address, amount, purpose, vozidla (list)}
    """
    today = today or date.today()
    os.makedirs(data_dir, exist_ok=True)
    ledger = os.path.join(data_dir, EVIDENCE_NAME)
    backup = os.path.join(data_dir, BACKUP_NAME)
    lock_fd = open(os.path.join(data_dir, _LOCK_NAME), "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        wb, ws = _open(ledger, "Faktury", _HEADER)
        wbb, wsb = _open(backup, "Záloha", _BACKUP_HEADER)
        year = today.year
        number = max(_max_in_year(ws, year), _max_in_year(wsb, year), number_prefix(year)) + 1
        vozidla = ", ".join(rec.get("vozidla") or [])
        issued, due = fmt_date(today), fmt_date(due_date(today))
        ws.append([number, issued, due, rec.get("payer", ""), rec.get("amount", ""),
                   rec.get("purpose", ""), vozidla])
        wsb.append([number, datetime.now().isoformat(timespec="seconds"), issued, due,
                    rec.get("payer", ""), rec.get("payer_ico", ""), rec.get("payer_address", ""),
                    rec.get("amount", ""), rec.get("purpose", ""), vozidla])
        # Backup first: if the ledger write then fails the number is still burnt.
        _atomic_save(wbb, backup)
        _atomic_save(wb, ledger)
        return number
    finally:
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()


def _read(path: str, keys: list) -> list:
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return []
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except Exception:
        return []
    rows = []
    try:
        for r in wb.active.iter_rows(min_row=2, values_only=True):
            if r and r[0] is not None:
                row = {k: (r[i] if i < len(r) else "") for i, k in enumerate(keys)}
                row["druh"] = DRUH
                rows.append(row)
    finally:
        wb.close()
    rows.sort(key=lambda x: x["cislo"] if isinstance(x["cislo"], int) else 0, reverse=True)
    return rows


def read_faktura_log(data_dir: str) -> list:
    """Live ledger, newest first; every row carries druh "faktura"."""
    return _read(os.path.join(data_dir, EVIDENCE_NAME),
                 ["cislo", "datum", "splatnost", "odberatel", "castka", "ucel", "vozidlo"])


def read_faktura_backup(data_dir: str) -> list:
    """Append-only backup, newest first (full record incl. address)."""
    return _read(os.path.join(data_dir, BACKUP_NAME),
                 ["cislo", "vystaveno", "datum", "splatnost", "odberatel", "ico",
                  "adresa", "castka", "ucel", "vozidla"])


def get_faktura(data_dir: str, number: int) -> dict | None:
    return next((r for r in read_faktura_backup(data_dir) if r.get("cislo") == number), None)


def pdf_record(rec: dict) -> dict:
    """Backup row -> input for faktura_pdf.build_faktura_pdf."""
    vozidla = [v.strip() for v in str(rec.get("vozidla") or "").split(",") if v.strip()]
    return {"number": rec["cislo"], "date": rec.get("datum", ""), "due": rec.get("splatnost", ""),
            "payer": rec.get("odberatel", ""), "payer_ico": rec.get("ico", ""),
            "payer_address": rec.get("adresa", ""), "amount": rec.get("castka", 0),
            "purpose": rec.get("ucel", ""), "vozidla": vozidla}
