from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
import db
from repositories import firmy_repo, ukony_repo, typy_repo, firma_ceny_repo
from services import ares_service

bp = Blueprint("firmy", __name__)


@bp.get("/firmy")
def index():
    conn = db.get_db()
    firmy = firmy_repo.list_all(conn)
    pocty = {f["id"]: ukony_repo.count_by_firma(conn, f["id"]) for f in firmy}
    return render_template("firmy.html", firmy=firmy, pocty=pocty)


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


@bp.post("/firmy/<int:fid>/smazat")
def delete(fid):
    conn = db.get_db()
    firma = firmy_repo.get(conn, fid)
    if not firma:
        abort(404)
    n = ukony_repo.count_by_firma(conn, fid)
    if n > 0:
        flash(f"Firmu „{firma['nazev']}“ nelze smazat — má {n} úkonů. Můžeš ji deaktivovat.", "error")
        return redirect(url_for("firmy.index"))
    firmy_repo.delete(conn, fid)
    flash(f"Firma „{firma['nazev']}“ smazána.", "success")
    return redirect(url_for("firmy.index"))


@bp.get("/firmy/ares")
def ares():
    out = ares_service.lookup_ico(request.args.get("ico", ""))
    if not out:
        return jsonify(ok=False), 404
    return jsonify(ok=True, **out)


@bp.get("/firmy/<int:fid>/ceny")
def ceny_form(fid):
    conn = db.get_db()
    firma = firmy_repo.get(conn, fid)
    if not firma:
        abort(404)
    return render_template(
        "firma_ceny.html",
        firma=firma,
        typy=typy_repo.list_active(conn),
        overrides=firma_ceny_repo.get_map(conn, fid),
    )


@bp.post("/firmy/<int:fid>/ceny")
def ceny_save(fid):
    conn = db.get_db()
    if not firmy_repo.get(conn, fid):
        abort(404)
    f = request.form
    bad = []
    for t in typy_repo.list_active(conn):
        raw = (f.get("cena_" + t["kod"]) or "").strip().replace(",", ".")
        if raw == "":
            firma_ceny_repo.set_price(conn, fid, t["kod"], None)  # revert to default
            continue
        try:
            val = float(raw)
            if val < 0:
                raise ValueError
        except ValueError:
            bad.append(t["kod"])
            continue
        firma_ceny_repo.set_price(conn, fid, t["kod"], val)
    if bad:
        flash("Neplatná cena u: " + ", ".join(bad) + " — přeskočeno.", "error")
    else:
        flash("Ceník uložen.", "success")
    return redirect(url_for("firmy.ceny_form", fid=fid))
