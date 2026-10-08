import re

from flask import Blueprint, request, jsonify
import db
from repositories import firmy_repo, typy_repo, ukony_repo
from services.ingest_service import pridat_ukon, UnknownFirmaError, ValidationError
from services import prichozi_service, pricing_service

bp = Blueprint("api", __name__)


@bp.get("/api/evidence-meta")
def evidence_meta():
    """Active firms + úkon types + each firm's effective price map, so the
    zadosti app can let the user pick the firm/type/price up front. Read-only;
    protected by the same X-Api-Key as the rest of /api/*."""
    conn = db.get_db()
    active = firmy_repo.list_all(conn, only_active=True)
    return jsonify({
        "firmy": [
            {"id": f["id"], "nazev": f["nazev"], "ico": f["ico"] or "", "zkratka": f["zkratka"]}
            for f in active
        ],
        "typy": [
            {"kod": t["kod"], "vychozi_cena": t["vychozi_cena"]}
            for t in typy_repo.list_active(conn)
        ],
        # {firma_id: {typ_kod: effective_price|null}} — lets the browser pre-fill
        # the price for the chosen firm+type without another round-trip.
        "ceny": {f["id"]: pricing_service.firm_price_map(conn, f["id"]) for f in active},
    })


@bp.post("/api/prichozi")
def intake_zadost():
    """Receive a finished žádost from the zadosti app. Auto-creates an úkon when
    a single active firm matches by IČO (převod/zápis), else queues it in the
    Příchozí inbox. Idempotent on `zadost_id`."""
    p = request.get_json(silent=True) or {}
    res = prichozi_service.intake(db.get_db(), p)
    code = 200 if res["status"] == "duplicate" else 201
    return jsonify(res), code


@bp.get("/api/ukony/hledat")
def hledat_ukony():
    vin = (request.args.get("vin") or "").strip().replace(" ", "")
    rz = (request.args.get("rz") or "").strip().replace(" ", "")
    if not vin and not rz:
        return jsonify(error="Zadejte VIN nebo RZ."), 400
    rows = ukony_repo.find_by_vehicle_any_firm(db.get_db(), vin=vin, rz=rz)
    return jsonify(ukony=[
        {
            "id": u["id"], "datum": u["datum"], "firma_id": u["firma_id"],
            "firma": u["firma"], "firma_zkratka": u["firma_zkratka"],
            "typ_kod": u["typ_kod"], "rz": u["rz"], "vin": u["vin"],
            "orv": u["orv"], "celkem": int(u["celkem"]),
        }
        for u in rows
    ])


def _normalize_vehicle_field(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("-", "")


@bp.post("/api/ukony/<int:uid>/doplnit")
def doplnit_ukon(uid):
    p = request.get_json(silent=True)
    if not isinstance(p, dict) or not any(field in p for field in ("rz", "orv")):
        return jsonify(error="Zadejte RZ nebo ORV."), 400

    values = {}
    for field, pattern in (("rz", r"[A-Z0-9]{5,8}"), ("orv", r"[A-Z]{3}[0-9]{6}")):
        if field not in p:
            continue
        value = p[field]
        if not isinstance(value, str):
            return jsonify(error=f"Neplatná hodnota {field.upper()}."), 400
        value = _normalize_vehicle_field(value)
        if not re.fullmatch(pattern, value):
            return jsonify(error=f"Neplatná hodnota {field.upper()}."), 400
        values[field] = value

    conn = db.get_db()
    ukon = ukony_repo.get(conn, uid)
    if ukon is None:
        return jsonify(error="Úkon nenalezen."), 404

    changes = {}
    for field, value in values.items():
        existing = ukon[field]
        if not existing or not existing.strip():
            changes[field] = value
        elif _normalize_vehicle_field(existing) != value:
            error = "RZ už je vyplněná jinak." if field == "rz" else "ORV už je vyplněné jinak."
            return jsonify(error=error, pole=field, stavajici=existing), 409

    # Check every requested field before writing any of them.
    if changes:
        ukony_repo.update(conn, uid, **changes)
    return jsonify(
        id=uid,
        rz=changes.get("rz", ukon["rz"]),
        orv=changes.get("orv", ukon["orv"]),
        zmeneno=list(changes),
    )


@bp.post("/api/ukony")
def create_ukon():
    p = request.get_json(silent=True) or {}
    try:
        uid = pridat_ukon(
            db.get_db(),
            firma_id=p.get("firma_id"),
            ico=p.get("ico"),
            datum=p.get("datum"),
            typ_kod=p.get("typ_kod"),
            celkem=p.get("celkem"),
            rz=p.get("rz"),
            vin=p.get("vin"),
            poznamka=p.get("poznamka"),
            zaplaceno_kc=p.get("zaplaceno_kc", 0),
            zdroj=p.get("zdroj", "prepis_app"),
        )
        return jsonify(id=uid), 201
    except (UnknownFirmaError, ValidationError) as e:
        return jsonify(error=str(e)), 400
