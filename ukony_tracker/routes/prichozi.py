"""Příchozí — inbox of incoming žádosti awaiting manual assignment."""
import json
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import db
from repositories import firmy_repo, typy_repo, prichozi_repo
from services import ingest_service as ing
from services import prichozi_service
from services import pricing_service

bp = Blueprint("prichozi", __name__)

# mode → suggested úkon type for the inbox type selector (zmena: user picks).
MODE_TYP = {"prevod": "PŘEVOD", "zapis": "NOVÉ", "zmena": ""}


@bp.get("/prichozi")
def inbox():
    conn = db.get_db()
    rows = prichozi_repo.list_by_status(conn, "pending")
    # Surface the vehicle make (znacka) from the stored payload — it helps
    # identify the firm at a glance (e.g. Volvo → Cardion). Convert each Row to
    # a dict so the template can read the extra `znacka` key alongside columns.
    items = []
    for r in rows:
        d = dict(r)
        try:
            raw = json.loads(r["raw_json"] or "{}")
            d["znacka"] = (raw.get("znacka") or "").strip()
            d["profil"] = (raw.get("profil") or "").strip()  # who filled it out in zadosti
        except (ValueError, TypeError):
            d["znacka"] = ""
            d["profil"] = ""
        # The note field is the operator's OWN note (empty by default); the
        # "z koho → na koho" transfer is shown separately by the party rows and
        # stored automatically on approve, so it never lands in poznámka.
        d["note"] = ""
        items.append(d)
    firmy = firmy_repo.list_all(conn, only_active=True)
    # Per-firm price maps so the inbox price field follows the chosen firm+type.
    firm_prices = {str(f["id"]): pricing_service.firm_price_map(conn, f["id"]) for f in firmy}
    return render_template(
        "prichozi.html",
        items=items,
        firmy=firmy,
        typy=typy_repo.list_active(conn),
        mode_typ=MODE_TYP,
        firm_prices_json=json.dumps(firm_prices),
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
            poznamka=(f.get("poznamka") or "").strip() or None,
            prevod=prichozi_service.context_note(dict(p)),  # auto transfer line
            zdroj="zadosti",
            zpracoval=(f.get("zpracoval") or "").strip() or None,
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
