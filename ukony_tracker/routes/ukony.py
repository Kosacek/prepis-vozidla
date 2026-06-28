import sqlite3
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
import db
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ingest_service as ing
from services import pricing_service
from services import colors_service

bp = Blueprint("ukony", __name__)


@bp.get("/ukony/hledat")
def hledat():
    """Live quick-find for the dashboard: returns the recent-row partial filtered
    by the query (VIN/RZ/ORV/poznámka/firma). Used to locate a freshly registered
    car so its úkon can be opened and the SPZ filled in."""
    conn = db.get_db()
    q = (request.args.get("q") or "").strip()
    rows = ukony_repo.search(conn, q) if q else []
    return render_template(
        "_recent_rows.html",
        rows=rows,
        firma_colors=colors_service.firma_color_map(conn),
        back="/",
        empty_text="Nic nenalezeno.",
    )


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
        ceny=pricing_service.firm_price_map(conn, firma_id),
        ukony=rows,
        total=total,
        pocet=len(rows),
        mesic=mesic,
        # After adding an úkon we carry the typ/date/price/note back so the next
        # car of the same kind can be added with only a fresh RZ/VIN. Absent on
        # first load → defaults (today, first typ, that typ's price, empty).
        dnes=request.args.get("datum") or date.today().isoformat(),
        sel_typ=request.args.get("typ") or "",
        sel_celkem=request.args.get("celkem"),
        sel_pozn=request.args.get("poznamka") or "",
        # RZ/VIN are only carried back on an error (so the input isn't lost);
        # on a successful add they stay empty, ready for the next car.
        sel_rz=request.args.get("rz") or "",
        sel_vin=request.args.get("vin") or "",
    )


@bp.post("/ukony/<int:firma_id>")
def add(firma_id):
    conn = db.get_db()
    if not firmy_repo.get(conn, firma_id):
        abort(404)
    f = request.form
    # Carry the typ/date/price/note back so the next car of the same kind can be
    # added with just a new RZ/VIN — those two fields are the only ones cleared.
    carry = {"mesic": f.get("mesic"), "datum": f.get("datum"),
             "typ": f.get("typ_kod"), "celkem": f.get("celkem")}
    if f.get("poznamka"):
        carry["poznamka"] = f.get("poznamka")
    try:
        ing.pridat_ukon(
            conn,
            firma_id=firma_id,
            datum=f.get("datum"),
            typ_kod=f.get("typ_kod"),
            celkem=f.get("celkem"),
            rz=f.get("rz") or None,
            vin=f.get("vin") or None,
            orv=f.get("orv") or None,
            poznamka=f.get("poznamka") or None,
        )
        flash("Úkon přidán.", "success")
    except ing.IngestError as e:
        flash(str(e), "error")
        # Nothing was saved — also keep RZ/VIN so the typed input isn't lost.
        if f.get("rz"):
            carry["rz"] = f.get("rz")
        if f.get("vin"):
            carry["vin"] = f.get("vin")
    return redirect(url_for("ukony.entry", firma_id=firma_id, **carry))


@bp.get("/ukony/vse")
def table():
    conn = db.get_db()
    firma_id = request.args.get("firma", type=int)
    mesic = request.args.get("mesic") or ""
    typ = request.args.get("typ") or None
    stav = request.args.get("stav") or None
    year = month = None
    if mesic:
        year, month = (int(x) for x in mesic.split("-"))
    rows = ukony_repo.list(conn, firma_id=firma_id, year=year, month=month, typ_kod=typ, stav=stav)
    total = sum(r["celkem"] for r in rows)
    return render_template(
        "ukony_table.html",
        ukony=rows,
        firmy=firmy_repo.list_all(conn),
        typy=typy_repo.list_active(conn),
        total=total,
        sel={"firma": firma_id, "mesic": mesic, "typ": typ, "stav": stav},
    )


@bp.get("/ukony/<int:uid>/upravit")
def edit_form(uid):
    conn = db.get_db()
    u = ukony_repo.get(conn, uid)
    if not u:
        abort(404)
    return render_template(
        "ukony_edit.html",
        u=u,
        typy=typy_repo.list_active(conn),
        firmy=firmy_repo.list_all(conn),
    )


@bp.post("/ukony/<int:uid>/upravit")
def edit_save(uid):
    conn = db.get_db()
    if not ukony_repo.get(conn, uid):
        abort(404)
    u = ukony_repo.get(conn, uid)
    f = request.form
    try:
        datum = (f.get("datum") or "").strip()
        date.fromisoformat(datum)  # reject blank/invalid so the date can't be wiped
        celkem = float(f.get("celkem") or 0)
        if celkem < 0:
            raise ValueError("záporná cena")
        # Re-derive payment state against the (possibly changed) celkem so the
        # table badge and the dashboard 'Nezaplaceno' KPI can never disagree.
        zaplaceno = min(float(u["zaplaceno_kc"]), celkem)
        stav = ing.derive_stav(celkem, zaplaceno)
        rz = (f.get("rz") or "").strip().upper() or None
        vin = (f.get("vin") or "").strip().upper() or None
        orv = (f.get("orv") or "").strip().upper() or None
        ukony_repo.update(
            conn, uid,
            datum=datum,
            rz=rz,
            typ_kod=f.get("typ_kod"),
            celkem=celkem,
            vin=vin,
            orv=orv,
            poznamka=f.get("poznamka") or None,
            zaplaceno_kc=zaplaceno,
            stav_platby=stav,
        )
        flash("Úkon upraven.", "success")
    except (ValueError, sqlite3.IntegrityError):
        flash("Neplatné hodnoty (zkontroluj datum a cenu).", "error")
    return redirect(f.get("back") or url_for("ukony.table"))


@bp.post("/ukony/<int:uid>/smazat")
def delete(uid):
    conn = db.get_db()
    ukony_repo.delete(conn, uid)
    flash("Úkon smazán.", "success")
    return redirect(request.form.get("back") or url_for("ukony.table"))


@bp.post("/ukony/<int:uid>/zaplaceno")
def mark_paid(uid):
    conn = db.get_db()
    u = ukony_repo.get(conn, uid)
    if not u:
        abort(404)
    castka = request.form.get("castka")
    try:
        z = float(castka) if castka else float(u["celkem"])
    except ValueError:
        z = float(u["celkem"])
    z = max(0.0, min(z, float(u["celkem"])))
    stav = ing.derive_stav(float(u["celkem"]), z)
    ukony_repo.update(conn, uid, zaplaceno_kc=z, stav_platby=stav)
    flash("Platba zaznamenána.", "success")
    return redirect(request.form.get("back") or url_for("ukony.table"))
