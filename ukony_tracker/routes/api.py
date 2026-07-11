from flask import Blueprint, request, jsonify
import db
from repositories import firmy_repo, typy_repo
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
