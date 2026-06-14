"""Příchozí — inbox of incoming žádosti awaiting manual assignment."""
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import db
from repositories import firmy_repo, typy_repo, prichozi_repo
from services import ingest_service as ing

bp = Blueprint("prichozi", __name__)

# mode → suggested úkon type for the inbox type selector (zmena: user picks).
MODE_TYP = {"prevod": "PŘEVOD", "zapis": "NOVÉ", "zmena": ""}


def _note(p) -> str | None:
    novy = (p["novy_jmeno"] or "").strip()
    puvodni = (p["puvodni_jmeno"] or "").strip()
    if novy and puvodni:
        return f"{novy} ← {puvodni}"
    return novy or puvodni or None


@bp.get("/prichozi")
def inbox():
    conn = db.get_db()
    return render_template(
        "prichozi.html",
        items=prichozi_repo.list_by_status(conn, "pending"),
        firmy=firmy_repo.list_all(conn, only_active=True),
        typy=typy_repo.list_active(conn),
        mode_typ=MODE_TYP,
    )


@bp.post("/prichozi/<int:pid>/approve")
def approve(pid):
    conn = db.get_db()
    p = prichozi_repo.get(conn, pid)
    if not p:
        abort(404)
    if p["status"] != "pending":
        flash("Tento záznam už byl vyřízen.", "error")
        return redirect(url_for("prichozi.inbox"))
    f = request.form
    try:
        firma_id = int(f.get("firma_id") or 0)
        datum = (f.get("datum") or "").strip()
        date.fromisoformat(datum)  # reject blank/invalid
        if not firma_id:
            raise ValueError("firma")
        uid = ing.pridat_ukon(
            conn,
            firma_id=firma_id,
            datum=datum,
            typ_kod=f.get("typ_kod"),
            celkem=f.get("celkem"),
            rz=p["rz"],
            vin=p["vin"],
            orv=p["orv"],
            poznamka=_note(p),
            zdroj="zadosti",
        )
        prichozi_repo.update(conn, pid, status="approved", created_ukon_id=uid)
        flash("Úkon vytvořen.", "success")
    except (ing.IngestError, ValueError):
        flash("Neplatné hodnoty — zkontroluj firmu, typ, cenu a datum.", "error")
    return redirect(url_for("prichozi.inbox"))


@bp.post("/prichozi/<int:pid>/discard")
def discard(pid):
    conn = db.get_db()
    if not prichozi_repo.get(conn, pid):
        abort(404)
    prichozi_repo.update(conn, pid, status="discarded")
    flash("Žádost zahozena.", "success")
    return redirect(url_for("prichozi.inbox"))
