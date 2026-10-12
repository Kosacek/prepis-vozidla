"""Příchozí — inbox of incoming žádosti awaiting manual assignment."""
import json
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import db
from repositories import firmy_repo, typy_repo, prichozi_repo, ukony_repo
from services import ingest_service as ing
from services import prichozi_service
from services import colors_service, pricing_service

bp = Blueprint("prichozi", __name__)

# mode → suggested úkon type for the inbox type selector (zmena: user picks).
MODE_TYP = {"prevod": "PŘEVOD", "zapis": "NOVÉ", "zmena": ""}


def _cena(v) -> str:
    """Cena z payloadu do hodnoty inputu: 1300.0 → '1300', prázdno když nepřišla."""
    if v in (None, ""):
        return ""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(v).strip()


def _dup_row(conn, uid):
    """The existing úkon as the list row shows it (with firma_zkratka)."""
    return conn.execute(
        "SELECT u.*, f.zkratka AS firma_zkratka FROM ukony u "
        "JOIN firmy f ON f.id=u.firma_id WHERE u.id=?", (uid,)).fetchone()


def _cena_cislo(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def incoming_preview(item: dict, dup, firma_by_id: dict) -> dict:
    """What approving this inbox item would create, shaped like an úkon row, plus
    the fields that differ from the already-existing duplicate."""
    typ = item["typ_kod"] or MODE_TYP.get(item.get("mode"), "")
    firma = firma_by_id.get(item.get("suggested_firma_id"))
    row = {
        "datum": item.get("datum") or "",
        "rz": item.get("rz") or "",
        "vin": item.get("vin") or "",
        "typ_kod": typ,
        "firma_zkratka": firma["zkratka"] if firma else "",
        "firma_id": firma["id"] if firma else None,
        "celkem": _cena_cislo(item["celkem"]),
        "poznamka": item["note"],
        "prevod": prichozi_service.context_note(item) or "",
        "zpracoval": item["profil"],
    }
    diffs, keys = [], []
    if dup is not None:
        if row["datum"] and row["datum"] != dup["datum"]:
            diffs.append("jiné datum"); keys.append("datum")
        if row["typ_kod"] and row["typ_kod"] != dup["typ_kod"]:
            diffs.append("jiný typ"); keys.append("typ")
        if row["firma_id"] and row["firma_id"] != dup["firma_id"]:
            diffs.append("jiná firma"); keys.append("firma")
        if row["celkem"] is not None and abs(row["celkem"] - (dup["celkem"] or 0)) > 0.5:
            diffs.append("jiná cena"); keys.append("cena")
    return {"row": row, "diffs": diffs, "diff_keys": keys, "same": dup is not None and not diffs}


@bp.get("/prichozi")
def inbox():
    conn = db.get_db()
    rows = prichozi_repo.list_by_status(conn, "pending")
    # Surface the vehicle make (znacka) from the stored payload — it helps
    # identify the firm at a glance (e.g. Volvo → Cardion). Convert each Row to
    # a dict so the template can read the extra `znacka` key alongside columns.
    firma_by_id = {f["id"]: f for f in firmy_repo.list_all(conn)}
    items = []
    for r in rows:
        d = dict(r)
        try:
            raw = json.loads(r["raw_json"] or "{}")
            d["znacka"] = (raw.get("znacka") or "").strip()
            d["profil"] = (raw.get("profil") or "").strip()  # who filled it out in zadosti
            # Hodnoty, které uživatel vybral už v Přepisu (karta „Evidence úkonu")
            # — musí přežít cestu do inboxu. Když se žádost zdrží (třeba kvůli
            # duplicitě), jinak by je musel psát znovu.
            d["note"] = (raw.get("poznamka") or "").strip()
            d["typ_kod"] = (raw.get("typ_kod") or "").strip()
            d["celkem"] = _cena(raw.get("celkem"))
        except (ValueError, TypeError):
            d["znacka"] = d["profil"] = d["note"] = d["typ_kod"] = d["celkem"] = ""
        # Held back as a possible duplicate → load the existing úkon so the card
        # can name it (číslo + datum) for the user's confirmation.
        dup_id = d.get("duplicate_ukon_id")
        d["dup"] = _dup_row(conn, dup_id) if dup_id else None
        d["incoming"] = incoming_preview(d, d["dup"], firma_by_id) if d["dup"] else None
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
        firma_colors=colors_service.firma_color_map(conn),
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
