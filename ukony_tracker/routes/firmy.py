from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
import db
from repositories import firmy_repo
from services import ares_service

bp = Blueprint("firmy", __name__)


@bp.get("/firmy")
def index():
    return render_template("firmy.html", firmy=firmy_repo.list_all(db.get_db()))


@bp.post("/firmy")
def create():
    conn = db.get_db()
    f = request.form
    if not (f.get("nazev") and f.get("zkratka")):
        flash("Název a zkratka jsou povinné.", "error")
        return redirect(url_for("firmy.index"))
    firmy_repo.create(
        conn,
        nazev=f["nazev"],
        zkratka=f["zkratka"],
        ico=f.get("ico") or None,
        adresa=f.get("adresa") or None,
        psc=f.get("psc") or None,
        poradi=int(f.get("poradi") or 0),
    )
    flash("Firma přidána.", "success")
    return redirect(url_for("firmy.index"))


@bp.post("/firmy/<int:fid>")
def update(fid):
    conn = db.get_db()
    if not firmy_repo.get(conn, fid):
        abort(404)
    f = request.form
    fields = {}
    for k in ("nazev", "zkratka", "ico", "adresa", "psc"):
        if k in f:
            fields[k] = f.get(k) or None
    if "poradi" in f:
        fields["poradi"] = int(f.get("poradi") or 0)
    fields["aktivni"] = 1 if f.get("aktivni") else 0
    if not fields.get("nazev") or not fields.get("zkratka"):
        flash("Název a zkratka jsou povinné.", "error")
        return redirect(url_for("firmy.index"))
    firmy_repo.update(conn, fid, **fields)
    flash("Firma upravena.", "success")
    return redirect(url_for("firmy.index"))


@bp.get("/firmy/ares")
def ares():
    out = ares_service.lookup_ico(request.args.get("ico", ""))
    if not out:
        return jsonify(ok=False), 404
    return jsonify(ok=True, **out)
