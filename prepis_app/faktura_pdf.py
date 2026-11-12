"""A5 invoice PDF (Faktura převodem s QR Platbou) — same look as the PPD.

build_faktura_pdf(record) -> bytes. Issuer details come from faktura.settings()
(env), a missing value prints the visible placeholder "[doplnit]". Without an
IBAN the QR is replaced by a grey box — a QR is never built from a fake account.
"""
from __future__ import annotations

import io

import segno
from reportlab.lib.colors import Color, black, lightgrey
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

import faktura
import ppd
import spayd

LEFT = 18 * mm
QR_SIZE = 32 * mm
MAX_VEHICLE_LINES = 5
QR_LABEL = "QR Platba"
QR_MISSING = "QR po doplnění IBAN"
IBAN_MISSING = "[doplnit IBAN]"


def spayd_for(record: dict, cfg: dict) -> str | None:
    """SPAYD string for the record, None when there is no usable IBAN."""
    try:
        iban = spayd.normalize_iban(cfg.get("iban", ""))
    except ValueError:
        return None
    vozidla = record.get("vozidla") or []
    ident = f"VIN {vozidla[0]}" if len(vozidla) == 1 and len(vozidla[0]) == 17 else ", ".join(vozidla)
    message = ident or f"Faktura {record.get('number', '')}"
    return spayd.build_spayd(iban, record.get("amount", 0), record.get("number", ""),
                             message, "ALSETA S.R.O.")


def _qr_bitmap(payload: str):
    """(rows of booleans) for the QR matrix, 4-module-free; quiet zone drawn by caller."""
    qr = segno.make(payload, error="m", micro=False)
    return [[bool(v) for v in row] for row in qr.matrix]


def _draw_qr(c, payload: str, x: float, y_top: float, size: float) -> None:
    matrix = _qr_bitmap(payload)
    n = len(matrix)
    cell = size / (n + 2)            # 1 module of quiet zone each side
    c.setFillColor(black)
    for r, row in enumerate(matrix):
        for col, dark in enumerate(row):
            if dark:
                c.rect(x + (col + 1) * cell, y_top - (r + 2) * cell, cell + 0.2, cell + 0.2,
                       stroke=0, fill=1)


def _draw_qr_missing(c, x: float, y_top: float, size: float, font: str) -> None:
    c.setFillColor(Color(0.88, 0.88, 0.88))
    c.setStrokeColor(Color(0.6, 0.6, 0.6))
    c.rect(x, y_top - size, size, size, stroke=1, fill=1)
    c.setFillColor(Color(0.35, 0.35, 0.35))
    c.setFont(font, 8)
    c.drawCentredString(x + size / 2, y_top - size / 2 - 2, QR_MISSING)
    c.setFillColor(black)
    c.setStrokeColor(black)


def _wrapped(c, font, size, text, x, y, width, leading) -> float:
    """Draw wrapped text, return the y below the last line."""
    c.setFont(font, size)
    for ln in simpleSplit(str(text), font, size, width):
        c.drawString(x, y, ln)
        y -= leading
    return y


def _party(c, font, x, y, width, label, lines) -> None:
    c.setFont(font, 8)
    c.setFillColor(Color(0.35, 0.35, 0.35))
    c.drawString(x, y, label)
    c.setFillColor(black)
    y -= 5 * mm
    for i, text in enumerate(lines):
        y = _wrapped(c, font, 10 if i == 0 else 8.5, text, x, y, width, 4.2 * mm)


def _supplier_lines(cfg: dict) -> list:
    lines = [cfg["name"], cfg["adresa"] or f"Sídlo: {faktura.PLACEHOLDER}",
             f"IČO: {cfg['ico']}", "Není plátce DPH",
             "Zapsána v obchodním rejstříku: " + (cfg["spisova_znacka"] or faktura.PLACEHOLDER)]
    return lines


def _customer_lines(record: dict) -> list:
    lines = [record.get("payer", "") or "-"]
    if record.get("payer_address"):
        lines.append(record["payer_address"])
    if record.get("payer_ico"):
        lines.append(f"IČO: {record['payer_ico']}")
    return lines


def _items(c, font, record, y, width) -> float:
    c.setLineWidth(0.5)
    c.setFont(font, 8)
    c.drawString(LEFT, y, "Položka")
    c.drawRightString(LEFT + width, y, "Cena")
    c.line(LEFT, y - 1.5 * mm, LEFT + width, y - 1.5 * mm)
    y -= 6 * mm
    c.setFont(font, 9.5)
    c.drawString(LEFT, y, str(record.get("purpose") or "Zastupování na MMB")[:60])
    c.drawRightString(LEFT + width, y, f"{record.get('amount', 0)} Kč")
    y -= 4.6 * mm
    vozidla = record.get("vozidla") or []
    shown = vozidla[:MAX_VEHICLE_LINES - 1] if len(vozidla) > MAX_VEHICLE_LINES else vozidla
    c.setFont(font, 8.5)
    for v in shown:
        c.drawString(LEFT + 3 * mm, y, ("VIN " if len(v) == 17 else "SPZ ") + v)
        y -= 4 * mm
    if len(shown) < len(vozidla):
        c.drawString(LEFT + 3 * mm, y, f"… a dalších {len(vozidla) - len(shown)} vozidel")
        y -= 4 * mm
    return y


def _payment(c, font, record, cfg, payload, H, width) -> None:
    top = H - 136 * mm
    c.setFont(font, 8)
    c.drawString(LEFT, top, "Platební údaje")
    qx = LEFT + width - QR_SIZE
    c.drawString(qx, top, QR_LABEL)
    if payload:
        _draw_qr(c, payload, qx, top - 2 * mm, QR_SIZE)
    else:
        _draw_qr_missing(c, qx, top - 2 * mm, QR_SIZE, font)
    ucet = (cfg["ucet"] or cfg["iban"]) if cfg["iban"] else IBAN_MISSING
    y = top - 6 * mm
    for label, value in (("Číslo účtu:", ucet), ("Variabilní symbol:", record.get("number", "")),
                         ("Splatnost:", record.get("due", ""))):
        c.setFont(font, 8)
        c.drawString(LEFT, y, label)
        c.setFont(font, 10)
        c.drawString(LEFT + 30 * mm, y, str(value))
        y -= 5 * mm
    if cfg["iban"] and cfg["ucet"]:
        c.setFont(font, 7.5)
        c.drawString(LEFT, y + 1 * mm, f"IBAN: {cfg['iban']}")
        y -= 2.5 * mm
    c.setFont(font, 9)
    c.drawString(LEFT, y - 3 * mm, "Celkem k úhradě:")
    c.setFont(font, 15)
    c.drawString(LEFT, y - 10 * mm, f"{record.get('amount', 0)} Kč")


def _watermark(c, font, W, H) -> None:
    c.saveState()
    c.setFillColor(Color(0.85, 0.85, 0.85))
    c.setFont(font, 70)
    c.translate(W / 2, H / 2)
    c.rotate(40)
    c.drawCentredString(0, 0, "VZOR")
    c.restoreState()


def build_faktura_pdf(record: dict, sample: bool = False) -> bytes:
    """Draw an A5 portrait faktura.

    record: {number, date, due, payer, payer_ico, payer_address, amount,
             purpose, vozidla (list)}
    """
    font = ppd._ensure_font()
    cfg = faktura.settings()
    W, H = A5
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    width = W - 2 * LEFT
    if sample:
        _watermark(c, font, W, H)
    c.setLineWidth(1)
    c.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm)
    c.setFont(font, 15)
    c.drawCentredString(W / 2, H - 24 * mm, "FAKTURA")
    c.setFont(font, 12)
    c.drawCentredString(W / 2, H - 31 * mm, f"č. {record.get('number', '')}")

    col = width / 2 - 2 * mm
    _party(c, font, LEFT, H - 41 * mm, col, "Dodavatel", _supplier_lines(cfg))
    _party(c, font, LEFT + width / 2 + 2 * mm, H - 41 * mm, col, "Odběratel", _customer_lines(record))

    c.setFont(font, 8.5)
    for i, (label, value) in enumerate((("Datum vystavení:", record.get("date", "")),
                                        ("Datum splatnosti:", record.get("due", "")),
                                        ("Forma úhrady:", "převodem"),
                                        ("Variabilní symbol:", record.get("number", "")))):
        x = LEFT + (width / 2 + 2 * mm) * (i % 2)
        y = H - (84 + 5.5 * (i // 2)) * mm
        c.drawString(x, y, f"{label} {value}")

    _items(c, font, record, H - 100 * mm, width)
    _payment(c, font, record, cfg, spayd_for(record, cfg), H, width)

    sy = 26 * mm
    c.setLineWidth(0.5)
    c.line(W - LEFT - 55 * mm, sy, W - LEFT, sy)
    c.setFont(font, 8)
    c.drawString(W - LEFT - 55 * mm, sy - 4.5 * mm, "Vystavil")
    if sample:
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawString(LEFT, sy - 4.5 * mm, "VZOR – není platný doklad")
        c.setFillColor(black)
    c.showPage()
    c.save()
    return ppd._mark_a5_print(buf.getvalue())
