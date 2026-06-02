"""Příjmový pokladní doklad (PPD) — cash-receipt generation.

Self-contained so the receipt logic stays out of the already-large app.py.
Three responsibilities:
  - amount_to_words_cs(n)            → Czech words with correct declension
  - reserve_ppd_number_and_log(...)  → atomic number allocation + ledger row
  - build_ppd_pdf(record)            → A5 receipt PDF bytes (reportlab)

Issuer is fixed: ALSETA s.r.o., IČO 07133880, neplátce DPH (no VAT line).
"""
from __future__ import annotations

import io
import os
import sys

import openpyxl
from num2words import num2words

# fcntl is POSIX-only. Production is the Linux container (where the flock is
# the real concurrency guard for gunicorn's 2 workers); on Windows dev we
# degrade to a no-op lock — single developer, no concurrency there.
try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows dev only
    _HAVE_FCNTL = False

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Issuer (fixed) ──────────────────────────────────────────────────────────
ISSUER_NAME = "ALSETA s.r.o."
ISSUER_ICO = "07133880"
ISSUER_NOTE = "neplátce DPH"

# ── Unicode font (Helvetica can't render ě/š/č/ř/ž) ─────────────────────────
_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
_FONT_PATH = os.path.join(_BASE_DIR, "static", "fonts", "DejaVuSans.ttf")
_FONT = "DejaVu"
_font_registered = False


def _ensure_font() -> str:
    """Register the Unicode TTF once; fall back to Helvetica if missing."""
    global _font_registered
    if _font_registered:
        return _FONT
    try:
        pdfmetrics.registerFont(TTFont(_FONT, _FONT_PATH))
        _font_registered = True
        return _FONT
    except Exception:
        return "Helvetica"  # degraded — diacritics may render as boxes


# ── Amount in words ─────────────────────────────────────────────────────────
def amount_to_words_cs(n: int) -> str:
    """Czech words for a whole-crown amount, correctly declined.

    num2words currency mode treats the integer as the minor unit (haléře),
    so we pass n*100 to get crown declension (koruna/koruny/korun), then drop
    the ", nula haléřů" tail (amounts are always whole crowns here).
    """
    try:
        words = num2words(int(n) * 100, lang="cs", to="currency", currency="CZK")
    except Exception:
        return ""
    return words.split(",", 1)[0].strip()


# ── Number allocation + evidence ledger (one lock) ──────────────────────────
EVIDENCE_NAME = "ppd_evidence.xlsx"
_LOCK_NAME = "ppd.lock"
_HEADER = ["Číslo", "Datum", "Přijato od", "Částka (Kč)", "Účel", "Vozidlo"]


def _evidence_path(data_dir: str) -> str:
    return os.path.join(data_dir, EVIDENCE_NAME)


def _max_number(ws) -> int:
    mx = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        try:
            v = int(row[0])
            if v > mx:
                mx = v
        except (TypeError, ValueError):
            continue
    return mx


def reserve_ppd_number_and_log(data_dir: str, record: dict) -> int:
    """Allocate the next sequential number AND append the evidence row under
    ONE exclusive lock, so two gunicorn workers can never collide and the
    number can never diverge from the ledger.

    record: {date, payer, amount, purpose, vehicle}
    Returns the allocated number.
    """
    os.makedirs(data_dir, exist_ok=True)
    lock_path = os.path.join(data_dir, _LOCK_NAME)
    path = _evidence_path(data_dir)

    lock_fd = open(lock_path, "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)  # blocking

        if os.path.exists(path) and os.path.getsize(path) > 0:
            wb = openpyxl.load_workbook(path)
            ws = wb.active
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "PPD"
            ws.append(_HEADER)

        number = _max_number(ws) + 1
        ws.append([
            number,
            record.get("date", ""),
            record.get("payer", ""),
            record.get("amount", ""),
            record.get("purpose", ""),
            record.get("vehicle", ""),
        ])

        # Atomic save: write temp, fsync, keep .bak, replace.
        tmp = path + ".tmp"
        wb.save(tmp)
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                import shutil
                shutil.copyfile(path, path + ".bak")
            except Exception:
                pass
        os.replace(tmp, path)
        return number
    finally:
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fd.close()


# ── A5 receipt PDF ──────────────────────────────────────────────────────────
def build_ppd_pdf(record: dict) -> bytes:
    """Draw an A5 portrait příjmový pokladní doklad.

    record: {number, date, payer, amount, purpose}
    """
    font = _ensure_font()
    buf = io.BytesIO()
    W, H = A5  # 419.5 x 595.3 pt (148 x 210 mm)
    c = canvas.Canvas(buf, pagesize=A5)

    number = record.get("number", "")
    date = record.get("date", "")
    payer = record.get("payer", "")
    amount = record.get("amount", "")
    purpose = record.get("purpose", "")
    words = amount_to_words_cs(amount) if isinstance(amount, int) else amount_to_words_cs(int(amount or 0))

    # Outer border
    c.setLineWidth(1)
    c.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm)

    # Title
    c.setFont(font, 15)
    c.drawCentredString(W / 2, H - 26 * mm, "PŘÍJMOVÝ POKLADNÍ DOKLAD")
    c.setFont(font, 12)
    c.drawCentredString(W / 2, H - 33 * mm, f"č. {number}")

    left = 18 * mm
    y = H - 48 * mm
    line_h = 9 * mm

    def field(label, value, big=False):
        nonlocal y
        c.setFont(font, 9)
        c.drawString(left, y, label)
        c.setFont(font, 13 if big else 11)
        c.drawString(left, y - 5.5 * mm, str(value))
        y -= line_h + (3 * mm if big else 0)

    # Issuer
    c.setFont(font, 10)
    c.drawString(left, y, f"Příjemce: {ISSUER_NAME}   IČO: {ISSUER_ICO}   ({ISSUER_NOTE})")
    y -= line_h
    c.setFont(font, 10)
    c.drawString(left, y, f"Datum: {date}")
    y -= line_h + 2 * mm

    field("Přijato od:", payer)
    field("Částka:", f"{amount} Kč", big=True)
    field("Slovy:", words)
    field("Účel platby:", purpose)

    # Signature lines near the bottom
    sy = 30 * mm
    c.setLineWidth(0.5)
    c.line(left, sy, left + 55 * mm, sy)
    c.line(W - left - 55 * mm, sy, W - left, sy)
    c.setFont(font, 8)
    c.drawString(left, sy - 5 * mm, "Vystavil")
    c.drawString(W - left - 55 * mm, sy - 5 * mm, "Podpis")

    c.showPage()
    c.save()
    return buf.getvalue()
