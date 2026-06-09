from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
import db
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ingest_service as ing

bp = Blueprint("ukony", __name__)


def _this_month():
    t = date.today()
    return f"{t.year:04d}-{t.month:02d}"


@bp.get("/ukony")
def entry_default():
    conn = db.get_db()
    firmy = firmy_repo.list_all(conn, only_active=True)
    if not firmy:
        return render_template(
            "ukony_entry.html",
            firmy=[],
            firma=None,
            typy=[],
            ukony=[],
            total=0,
            pocet=0,
            mesic=_this_month(),
            dnes=date.today().isoformat(),
        )
    return redirect(url_for("ukony.entry", firma_id=firmy[0]["id"]))


@bp.get("/ukony/<int:firma_id>")
def entry(firma_id):
    conn = db.get_db()
    firma = firmy_repo.get(conn, firma_id)
    if not firma:
        abort(404)
    mesic = request.args.get("mesic") or _this_month()
    year, month = (int(x) for x in mesic.split("-"))
    rows = ukony_repo.list(conn, firma_id=firma_id, year=year, month=month)
    total = sum(r["celkem"] for r in rows)
    return render_template(
        "ukony_entry.html",
        firmy=firmy_repo.list_all(conn, only_active=True),
        firma=firma,
        typy=typy_repo.list_active(conn),
        ukony=rows,
        total=total,
        pocet=len(rows),
        mesic=mesic,
        dnes=date.today().isoformat(),
    )


@bp.post("/ukony/<int:firma_id>")
def add(firma_id):
    conn = db.get_db()
    if not firmy_repo.get(conn, firma_id):
        abort(404)
    f = request.form
    try:
        ing.pridat_ukon(
            conn,
            firma_id=firma_id,
            datum=f.get("datum"),
            typ_kod=f.get("typ_kod"),
            celkem=f.get("celkem"),
            rz=f.get("rz") or None,
            vin=f.get("vin") or None,
            poznamka=f.get("poznamka") or None,
        )
        flash("Úkon přidán.", "success")
    except ing.IngestError as e:
        flash(str(e), "error")
    return redirect(url_for("ukony.entry", firma_id=firma_id, mesic=f.get("mesic")))
