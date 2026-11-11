"""Session-authenticated ORV fragment and one-photo endpoint."""
import logging
import os
import re
import time
import uuid

from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import db
import config
from repositories import firmy_repo, typy_repo
from services import orv_images, orv_scan_service, pricing_service, colors_service
from services.vehicle_fill_service import transaction
from services.ingest_service import normalize_profil

bp = Blueprint("orv_scan", __name__)
logger = logging.getLogger("orvsken")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False


def _session_id():
    if "orvsken_sid" not in session:
        session["orvsken_sid"] = uuid.uuid4().hex
    return session["orvsken_sid"]


def _rate_allowed(conn):
    # Shared by gunicorn workers and serialized across concurrent photos.
    sid, now = _session_id(), time.time()
    with transaction(conn):
        conn.execute("DELETE FROM orv_scan_rate WHERE stamp <= ?", (now - 600,))
        count = conn.execute("SELECT COUNT(*) FROM orv_scan_rate WHERE sid=?", (sid,)).fetchone()[0]
        if count >= 60:
            return False
        conn.execute("INSERT INTO orv_scan_rate(sid, stamp) VALUES (?, ?)", (sid, now))
    return True


@bp.get("/ukony/orv-sken")
def fragment():
    _session_id()  # Set cookie before the browser launches parallel uploads.
    conn = db.get_db()
    types = typy_repo.list_active(conn)
    firmy = firmy_repo.list_all(conn, only_active=True)
    # Ceny pro kartu zakládaného auta (firma × typ); šablona je vloží jako JSON.
    ceny = {str(f["id"]): pricing_service.firm_price_map(conn, f["id"]) for f in firmy}
    # Barvy firem = stejná paleta jako v Úkonech (tečka u firmy v kartě skenu).
    colors = colors_service.firma_color_map(conn)
    firma_colors = {f["zkratka"]: colors.get(f["zkratka"], "#8e8e93") for f in firmy}
    firmy_data = [{"id": f["id"], "nazev": f["nazev"], "zkratka": f["zkratka"],
                   "color": colors.get(f["zkratka"], "#8e8e93")} for f in firmy]
    return render_template("_orv_sken.html", firmy=firmy, typy=types, profily=config.PROFILY,
                           ceny=ceny, firma_colors=firma_colors, firmy_data=firmy_data), \
        200, {"Cache-Control": "no-store"}


def _clean_poznamka(value):
    """Optional note for the created úkon: trimmed/collapsed, ≤120 chars, never
    a spreadsheet formula. Blank means no note."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Neplatná poznámka.")
    note = re.sub(r"\s+", " ", value).strip()
    if not note:
        return None
    if note.startswith("="):
        raise ValueError("Poznámka nesmí začínat znakem „=“.")
    if len(note) > 120:
        raise ValueError("Poznámka smí mít nejvýše 120 znaků.")
    return note


@bp.post("/ukony/orv-sken")
def scan():
    start = time.monotonic()
    result = {"stav": "chyba", "ukon": None}
    orv_scan_service.tokens.set(0)
    orv_scan_service.raw_orv.set(())
    try:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return jsonify(error="Čtení fotek není nastavené."), 503
        conn = db.get_db()
        if not _rate_allowed(conn):
            return jsonify(error="Limit 60 fotek za 10 minut. Zkuste to za chvíli."), 429
        files = list(request.files.items(multi=True))
        if len(files) != 1 or files[0][0] != "foto":
            return jsonify(error="Pošlete právě jednu fotku v poli foto."), 400
        data = files[0][1].read(orv_images.MAX_IMAGE_BYTES + 1)
        if len(data) > orv_images.MAX_IMAGE_BYTES:
            raise RequestEntityTooLarge()
        image_bytes, media_type = orv_images.prepare(data)
        result = orv_scan_service.zpracuj(conn, image_bytes, media_type,
                                          zpracoval=normalize_profil(request.form.get("zpracoval")))
        return jsonify(result)
    except RequestEntityTooLarge:
        return jsonify(error="Fotka smí mít nejvýše 8 MB."), 413
    except (ValueError, BadRequest) as exc:
        return jsonify(error=str(exc) if isinstance(exc, ValueError) else "Neplatné nahrání fotky."), 400
    except Exception:
        return jsonify(error="Fotku se nepodařilo zpracovat. Zkuste to znovu."), 500
    finally:
        # What the reader actually saw (no names): "UB0056935" explains a
        # "nečitelné" that a bare state never did (2026-11-11, 4444PARK).
        logger.info("stav=%s ukon=%s ms=%d cteni=%d tokens=%d rz=%s orv=%s cteno=%s", result["stav"],
                    (result.get("ukon") or {}).get("id", "-"),
                    round((time.monotonic() - start) * 1000), 2 if result.get("druhe_cteni") else 1,
                    orv_scan_service.tokens.get(), result.get("rz") or "-",
                    result.get("orv_cislo") or "-", ",".join(orv_scan_service.raw_orv.get()) or "-")


@bp.post("/ukony/orv-sken/zalozit")
def zalozit():
    """Create only cars selected in the unmatched-firm review card."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("auta"), list):
        return jsonify(error="Pošlete seznam aut."), 400
    auta = payload["auta"]
    if not auta or len(auta) > 30:
        return jsonify(error="Vyberte 1 až 30 aut."), 400
    conn = db.get_db()
    if not _rate_allowed(conn):
        return jsonify(error="Limit skenování za 10 minut. Zkuste to za chvíli."), 429
    active_firms = {f["id"]: f for f in firmy_repo.list_all(conn, only_active=True)}
    active_types = {t["kod"] for t in typy_repo.list_active(conn)}
    prepared = []
    for item in auta:
        if not isinstance(item, dict) or set(item) - {
                "rz", "vin", "orv_cislo", "firma_id", "typ_kod", "provozovatel", "vin_zdroj",
                "poznamka", "potvrdit_novy"}:
            return jsonify(error="Neplatný záznam auta."), 400
        rz, vin, orv = item.get("rz"), item.get("vin"), item.get("orv_cislo")
        def clean(value, pattern):
            if value is None or value == "":
                return None
            if not isinstance(value, str):
                raise ValueError("Neplatné údaje vozidla.")
            normalized = value.strip().upper().replace(" ", "").replace("-", "")
            if not re.fullmatch(pattern, normalized):
                raise ValueError("Neplatné údaje vozidla.")
            return normalized
        try:
            rz = clean(rz, r"[A-Z0-9]{5,8}")
            vin = clean(vin, r"[A-Z0-9]{5,17}")
            orv = clean(orv, r"[A-Z]{3}[0-9]{6}")
            poznamka = _clean_poznamka(item.get("poznamka"))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if not rz and not vin:
            return jsonify(error="Auto musí mít RZ nebo VIN."), 400
        firm_id, typ_kod = item.get("firma_id"), item.get("typ_kod")
        if isinstance(firm_id, bool) or not isinstance(firm_id, int) or firm_id not in active_firms:
            return jsonify(error="Vyberte aktivní firmu."), 400
        if not isinstance(typ_kod, str) or typ_kod not in active_types:
            return jsonify(error="Vyberte aktivní typ úkonu."), 400
        operator = item.get("provozovatel")
        if operator is not None and (not isinstance(operator, str) or len(operator.strip()) > 120):
            return jsonify(error="Neplatné jméno provozovatele."), 400
        vin_zdroj = item.get("vin_zdroj")
        if vin_zdroj not in (None, "foto", "registr"):
            return jsonify(error="Neplatný zdroj VIN."), 400
        potvrdit_novy = item.get("potvrdit_novy")
        if potvrdit_novy is not None and not isinstance(potvrdit_novy, bool):
            return jsonify(error="Neplatné potvrzení nového úkonu."), 400
        prepared.append(({"rz": rz, "vin": vin, "orv_cislo": orv,
                          "provozovatel": operator.strip() if operator else None,
                          "vin_zdroj": vin_zdroj}, firm_id, typ_kod, poznamka, potvrdit_novy))
    zpracoval = normalize_profil(payload.get("zpracoval"))
    try:
        results = []
        with transaction(conn):
            for data, firma_id, typ_kod, poznamka, potvrdit_novy in prepared:
                results.append(orv_scan_service.zalozit_pro_firmu(
                    conn, data, firma_id=firma_id, typ_kod=typ_kod, zpracoval=zpracoval,
                    poznamka=poznamka, potvrdit_novy=potvrdit_novy))
        return jsonify(results=results)
    except Exception:
        return jsonify(error="Úkony se nepodařilo založit."), 500
