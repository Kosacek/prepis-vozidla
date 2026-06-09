from flask import Blueprint, render_template, request, redirect, url_for, flash
import db
from repositories import typy_repo

bp = Blueprint("nastaveni", __name__)


@bp.get("/nastaveni")
def index():
    return render_template("nastaveni.html", typy=typy_repo.list_all(db.get_db()))


@bp.post("/nastaveni")
def save():
    conn = db.get_db()
    f = request.form
    kod = (f.get("kod") or "").strip()
    if not kod:
        flash("Kód typu je povinný.", "error")
        return redirect(url_for("nastaveni.index"))
    cena = f.get("vychozi_cena")
    cena = float(cena) if cena else None
    aktivni = 1 if f.get("aktivni") else 0
    typy_repo.upsert(conn, kod, cena, int(f.get("poradi") or 0), aktivni)
    flash("Uloženo.", "success")
    return redirect(url_for("nastaveni.index"))
