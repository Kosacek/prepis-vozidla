"""Excel and CSV export for úkony data."""
import csv as csvmod
import io
from sqlite3 import Connection

import openpyxl

from repositories import firmy_repo, ukony_repo

# Column order for the Excel header row
HEAD = ["Datum", "RZ", "Úkon", "Celkem", "VIN", "Poznámka", "Zaplaceno", "Zaplaceno Kč"]


def export_excel(conn: Connection, year: int, month: int | None = None) -> bytes:
    """Return an Excel workbook (.xlsx) as raw bytes.

    One sheet per firma that has úkony in the requested period.  The last row
    of each sheet is a CELKEM totals row.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove the default empty sheet

    for f in firmy_repo.list_all(conn):
        rows = ukony_repo.list(conn, firma_id=f["id"], year=year, month=month)
        if not rows:
            continue

        # Sheet title: zkratka preferred, truncated to 31 chars (Excel limit)
        title = (f["zkratka"] or f["nazev"])[:31]
        ws = wb.create_sheet(title=title)
        ws.append(HEAD)

        total = 0.0
        for u in sorted(rows, key=lambda r: r["datum"]):
            ws.append([
                u["datum"],
                u["rz"],
                u["typ_kod"],
                u["celkem"],
                u["vin"],
                u["poznamka"],
                u["stav_platby"],
                u["zaplaceno_kc"],
            ])
            total += u["celkem"]

        # Totals row: label in column A, sum in the Celkem column (index 4)
        ws.append([f"CELKEM ({len(rows)} úkonů)", "", "", total, "", "", "", ""])

    if not wb.sheetnames:
        wb.create_sheet(title="Prázdné")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_csv(conn: Connection, date_from: str, date_to: str) -> str:
    """Return all úkony in [date_from, date_to] as a CSV string."""
    rows = conn.execute(
        "SELECT u.datum, f.zkratka firma, u.rz, u.typ_kod, u.celkem, u.vin, "
        "u.poznamka, u.stav_platby, u.zaplaceno_kc "
        "FROM ukony u JOIN firmy f ON f.id=u.firma_id "
        "WHERE u.datum BETWEEN ? AND ? "
        "ORDER BY u.datum",
        (date_from, date_to),
    ).fetchall()

    buf = io.StringIO()
    w = csvmod.writer(buf)
    w.writerow(["datum", "firma", "rz", "typ", "celkem", "vin", "poznamka", "stav_platby", "zaplaceno_kc"])
    for r in rows:
        w.writerow([r[k] for k in r.keys()])
    return buf.getvalue()
