from flask import Blueprint, request, jsonify
import db
from services.ingest_service import pridat_ukon, UnknownFirmaError, ValidationError
from services import prichozi_service

bp = Blueprint("api", __name__)


@bp.post("/api/prichozi")
def intake_zadost():
    """Receive a finished žádost from the zadosti app. Auto-creates an úkon when
    a single active firm matches by IČO (převod/zápis), else queues it in the
    Příchozí inbox. Idempotent on `zadost_id`."""
    p = request.get_json(silent=True) or {}
    res = prichozi_service.intake(db.get_db(), p)
    code = 200 if res["status"] == "duplicate" else 201
    return jsonify(res), code


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
