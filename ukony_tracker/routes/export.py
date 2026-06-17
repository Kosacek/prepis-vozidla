import io
from datetime import date

from flask import Blueprint, render_template, request, send_file

import db
from repositories import firmy_repo
from services import export_service

bp = Blueprint("export", __name__)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _range():
    """(from, to) from the request, defaulting to Jan-1-this-year … today."""
    t = date.today()
    dfrom = request.args.get("from") or f"{t.year}-01-01"
    dto = request.args.get("to") or t.isoformat()
    return dfrom, dto


def _filename(conn, ext, dfrom, dto, firma_ids):
    if len(firma_ids) == 1:
        f = firmy_repo.get(conn, firma_ids[0])
        tag = "_" + (f["zkratka"] or f["nazev"]).replace(" ", "_") if f else ""
    elif firma_ids:
        tag = f"_{len(firma_ids)}firem"
    else:
        tag = "_vse"
    return f"ukony_{dfrom}_{dto}{tag}.{ext}"


@bp.get("/export")
def index():
    t = date.today()
    return render_template(
        "export.html",
        dfrom=f"{t.year}-01-01",
        dto=t.isoformat(),
        firmy=firmy_repo.list_all(db.get_db()),
    )


@bp.get("/export/excel")
def excel():
    conn = db.get_db()
    dfrom, dto = _range()
    firma_ids = request.args.getlist("firma", type=int)
    data = export_service.export_excel(conn, dfrom, dto, firma_ids or None)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=_filename(conn, "xlsx", dfrom, dto, firma_ids),
        mimetype=_XLSX_MIME,
    )


@bp.get("/export/csv")
def csv():
    conn = db.get_db()
    dfrom, dto = _range()
    firma_ids = request.args.getlist("firma", type=int)
    text = export_service.export_csv(conn, dfrom, dto, firma_ids or None)
    return send_file(
        io.BytesIO(text.encode("utf-8-sig")),
        as_attachment=True,
        download_name=_filename(conn, "csv", dfrom, dto, firma_ids),
        mimetype="text/csv",
    )
