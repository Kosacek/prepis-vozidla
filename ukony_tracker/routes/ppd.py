"""Příjem PPD ze zadosti a přehled dokladů v evidenci."""
import calendar
import re
from datetime import date

from flask import Blueprint, abort, jsonify, render_template, request

import db
from repositories import firmy_repo, ppd_repo, ukony_repo
from services import colors_service, ppd_links

bp = Blueprint("ppd", __name__)


@bp.put("/api/ppd/<int:cislo>")
def put_doklad(cislo):
    # /api/ chrání společná kontrola X-Api-Key v app.py.
    record = request.get_json(silent=True)
    if not isinstance(record, dict):
        return jsonify(error="Doklad musí být JSON objekt."), 400
    if "cislo" in record and (type(record["cislo"]) is not int or record["cislo"] != cislo):
        return jsonify(error="Číslo dokladu v těle musí souhlasit s číslem v URL."), 400
    try:
        row, created = ppd_repo.upsert(db.get_db(), {**record, "cislo": cislo})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(dict(row)), 201 if created else 200


@bp.post("/api/ppd/import")
def import_doklady():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("doklady"), list):
        return jsonify(error="Očekáván JSON objekt se seznamem doklady."), 400
    conn = db.get_db()
    result = {"vytvoreno": 0, "aktualizovano": 0, "chyby": []}
    for record in payload["doklady"]:
        try:
            _, created = ppd_repo.upsert(conn, record)
        except ValueError as e:
            result["chyby"].append({
                "cislo": record.get("cislo") if isinstance(record, dict) else None,
                "error": str(e),
            })
            continue
        result["vytvoreno" if created else "aktualizovano"] += 1
    return jsonify(result)


@bp.get("/doklady")
def doklady():
    # Běžná stránka používá stejnou session bránu jako přehled úkonů. Firma,
    # měsíc a smazané filtruje server (odkaz jde uložit), hledání i živě v JS.
    mesic = (request.args.get("mesic") or "").strip()
    q = (request.args.get("q") or "").strip()
    smazane = request.args.get("smazane") == "1"
    firma = request.args.get("firma", type=int)
    od = do = None
    if mesic:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}", mesic):
                raise ValueError
            first = date.fromisoformat(mesic + "-01")
            od = first.isoformat()
            do = first.replace(day=calendar.monthrange(first.year, first.month)[1]).isoformat()
        except ValueError:
            abort(400, description="Neplatný měsíc.")
    conn = db.get_db()
    links = ppd_links.for_request()
    rows = [r for r in ppd_repo.list(conn, od=od, do=do, q=q, include_deleted=smazane, limit=None)
            if firma is None or links.firma.get(r["cislo"]) == firma]
    ukony = ukony_repo.list_by_ids(conn, (uid for r in rows for uid in links.by_doklad.get(r["cislo"], [])))
    firmy = firmy_repo.list_all(conn)
    return render_template(
        "doklady.html", doklady=rows, links=links, ukony=ukony,
        firmy=firmy, firmy_by_id={f["id"]: f for f in firmy},
        firma_colors=colors_service.firma_color_map(conn),
        total={"pocet": len(rows), "castka": sum(r["castka"] for r in rows)},
        mesic=mesic, q=q, smazane=smazane, firma=firma,
        auta=ppd_links.auta, back_url=request.full_path.rstrip("?"),
    )
