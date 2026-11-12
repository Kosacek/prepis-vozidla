"""A5 invoice PDF (Faktura převodem s QR Platbou) — same look as the PPD.

build_faktura_pdf(record) -> bytes. Issuer details come from faktura.settings()
(env), a missing value prints the visible placeholder "[doplnit]". Without an
IBAN the QR is replaced by a grey box — a QR is never built from a fake account.
"""
from __future__ import annotations

import io
import re

import segno
from reportlab.lib.colors import Color, black, lightgrey
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import faktura
import ppd
import spayd

LEFT = 18 * mm
QR_SIZE = 36 * mm
PLATE_FONT = "Helvetica-Bold"   # built-in; capitals (J, Q…) all sit on the baseline
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


GREY = Color(0.35, 0.35, 0.35)
NBSP = " "
_ONE_LETTER = re.compile(r"(?<!\S)([AaIiKkOoSsUuVvZz]) ")


def _glue_prepositions(text: str) -> str:
    """Czech typography: a one-letter word never ends a line (u Krajského, v Brně)."""
    return _ONE_LETTER.sub(lambda m: m.group(1) + NBSP, text)


def _split(text: str, font: str, size: float, width: float) -> list:
    """Greedy wrap on plain spaces only, so NBSP keeps words together."""
    lines, cur = [], ""
    for word in _glue_prepositions(str(text)).split(" "):
        trial = f"{cur} {word}" if cur else word
        if cur and stringWidth(trial.replace(NBSP, " "), font, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return [ln.replace(NBSP, " ") for ln in lines]


def _party(c, font, x, y, width, label, lines, notes=()) -> None:
    """Name (10 pt), address/IČO (8 pt), then small grey legal notes (6.5 pt)."""
    c.setFont(font, 8)
    c.setFillColor(GREY)
    c.drawString(x, y, label)
    c.setFillColor(black)
    y -= 5 * mm
    for i, text in enumerate(lines):
        size = 10 if i == 0 else 8
        c.setFont(font, size)
        for ln in _split(text, font, size, width):
            c.drawString(x, y, ln)
            y -= (4.4 if i == 0 else 3.8) * mm
    c.setFillColor(GREY)
    c.setFont(font, 6.5)
    for text in notes:
        for ln in _split(text, font, 6.5, width):
            c.drawString(x, y, ln)
            y -= 3 * mm
    c.setFillColor(black)


def _supplier_lines(cfg: dict) -> list:
    adresa = cfg["adresa"] or f"Sídlo: {faktura.PLACEHOLDER}"
    ulice, _, mesto = adresa.rpartition(",")
    adresa_lines = [ulice.strip(), mesto.strip()] if ulice else [adresa]
    return [cfg["name"], *adresa_lines, f"IČO: {cfg['ico']}"]


def _supplier_notes(cfg: dict) -> list:
    return ["Není plátce DPH.",
            "Zapsána v obchodním rejstříku, sp." + NBSP + "zn." + NBSP
            + _glue_mark(cfg["spisova_znacka"] or faktura.PLACEHOLDER) + "."]


def _glue_mark(znacka: str) -> str:
    """'C 106352 vedená…' -> keep the 'C 106352' part on one line."""
    return re.sub(r"^(\S{1,3}) (\d)", lambda m: m.group(1) + NBSP + m.group(2), znacka)


def _iban_display(iban: str) -> str:
    """CZ6508000000192000145399 -> 'CZ65 0800 0000 1920 0014 5399'."""
    raw = "".join(str(iban).split()).upper()
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))


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
    c.drawRightString(LEFT + width, y, _money(record.get('amount', 0)))
    y -= 4.6 * mm
    vozidla = record.get("vozidla") or []
    shown = vozidla[:MAX_VEHICLE_LINES - 1] if len(vozidla) > MAX_VEHICLE_LINES else vozidla
    for v in shown:
        c.setFont(font, 7.5)
        c.setFillColor(GREY)
        c.drawString(LEFT + 3 * mm, y, "VIN" if len(v) == 17 else "SPZ")
        c.setFillColor(black)
        t = c.beginText(LEFT + 10 * mm, y)
        t.setFont(PLATE_FONT, 9)
        t.setCharSpace(0.7)             # light tracking keeps VIN characters apart
        t.textOut(_ascii(v))
        c.drawText(t)
        y -= 4.2 * mm
    c.setFont(font, 8.5)
    if len(shown) < len(vozidla):
        c.drawString(LEFT + 3 * mm, y, f"… a dalších {len(vozidla) - len(shown)} vozidel")
        y -= 4 * mm
    return y


def _ascii(text: str) -> str:
    """Helvetica is a Latin-1 base font; VIN/SPZ are plain A-Z0-9 anyway."""
    return str(text).encode("ascii", "replace").decode("ascii")


def _money(amount) -> str:
    """1500 -> '1 500,00 Kč' (Czech grouping, two decimals)."""
    try:
        txt = f"{float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{amount} Kč"
    return txt.replace(",", " ").replace(".", ",") + " Kč"


def _payment(c, font, record, cfg, payload, H, width) -> None:
    """Bottom block: QR Platba left with the bank details under it (for anyone
    who can't scan), total top-right."""
    top = H - 131 * mm
    right = LEFT + width
    if payload:
        _draw_qr(c, payload, LEFT, top, QR_SIZE)
    else:
        _draw_qr_missing(c, LEFT, top, QR_SIZE, font)
    c.setFont(font, 8)
    c.setFillColor(GREY)
    c.drawCentredString(LEFT + QR_SIZE / 2, top - QR_SIZE - 4 * mm, QR_LABEL)

    c.drawRightString(right, top + 3 * mm, "Celkem k úhradě")
    amount = _money(record.get("amount", 0))
    c.setFillColor(black)
    c.saveState()
    c.setLineWidth(0.7)
    t = c.beginText(right - c.stringWidth(amount, font, 19), top - 5 * mm)
    t.setFont(font, 19)
    t.setTextRenderMode(2)          # fill + stroke = faux bold (one TTF only)
    t.textOut(amount)
    c.drawText(t)
    c.restoreState()
    _bank_details(c, font, record, cfg, LEFT, top - QR_SIZE - 9.5 * mm)


def _bank_details(c, font, record, cfg, x, y) -> None:
    if cfg["iban"]:
        rows = [("Číslo účtu", cfg["ucet"] or _iban_display(cfg["iban"])),
                ("IBAN", _iban_display(cfg["iban"]))]
    else:
        rows = [("Číslo účtu", IBAN_MISSING)]
    rows += [("Variabilní symbol", record.get("number", ""))]
    for label, value in rows:
        c.setFont(font, 6.5)
        c.setFillColor(GREY)
        c.drawString(x, y, label)
        c.setFont(font, 8.5)
        c.setFillColor(black)
        c.drawString(x + 25 * mm, y, str(value))
        y -= 4.2 * mm


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
    _party(c, font, LEFT, H - 41 * mm, col, "Dodavatel", _supplier_lines(cfg),
           _supplier_notes(cfg))
    _party(c, font, LEFT + width / 2 + 2 * mm, H - 41 * mm, col, "Odběratel", _customer_lines(record))

    c.setFont(font, 8.5)
    for i, (label, value) in enumerate((("Datum vystavení:", record.get("date", "")),
                                        ("Datum splatnosti:", record.get("due", "")),
                                        ("Forma úhrady:", "převodem"),
                                        ("Variabilní symbol:", record.get("number", "")))):
        x = LEFT + (width / 2 + 2 * mm) * (i % 2)
        y = H - (84 + 5.5 * (i // 2)) * mm
        c.drawString(x, y, f"{label} {value}")

    _items(c, font, record, H - 98 * mm, width)
    _payment(c, font, record, cfg, spayd_for(record, cfg), H, width)

    if sample:
        c.setFont(font, 8)
        c.setFillColor(Color(0.5, 0.5, 0.5))
        c.drawString(LEFT, 17 * mm, "VZOR – není platný doklad")
        c.setFillColor(black)
    c.showPage()
    c.save()
    return ppd._mark_a5_print(buf.getvalue())
