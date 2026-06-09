import io
from datetime import date
from flask import Blueprint, render_template, request, send_file
import db
from repositories import firmy_repo
from services import export_service

bp = Blueprint("export", __name__)


@bp.get("/export")
def index():
    t = date.today()
    return render_template("export.html", year=t.year, month=t.month,
                           firmy=firmy_repo.list_all(db.get_db()))


@bp.get("/export/excel")
def excel():
    conn = db.get_db()
    year = request.args.get("year", type=int) or date.today().year
    month = request.args.get("month", type=int) or None
    firma_id = request.args.get("firma", type=int) or None
    data = export_service.export_excel(conn, year, month, firma_id=firma_id)
    suffix = ""
    if firma_id:
        f = firmy_repo.get(conn, firma_id)
        if f:
            suffix = "_" + (f["zkratka"] or f["nazev"]).replace(" ", "_")
    name = f"ukony_{year}" + (f"-{month:02d}" if month else "") + suffix + ".xlsx"
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/export/csv")
def csv():
    conn = db.get_db()
    dfrom = request.args.get("from") or f"{date.today().year}-01-01"
    dto = request.args.get("to") or f"{date.today().year}-12-31"
    text = export_service.export_csv(conn, dfrom, dto)
    return send_file(
        io.BytesIO(text.encode("utf-8-sig")),
        as_attachment=True,
        download_name=f"ukony_{dfrom}_{dto}.csv",
        mimetype="text/csv",
    )
