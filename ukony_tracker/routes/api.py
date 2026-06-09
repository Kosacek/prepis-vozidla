from flask import Blueprint, request, jsonify
import db
from services.ingest_service import pridat_ukon, UnknownFirmaError, ValidationError

bp = Blueprint("api", __name__)


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
