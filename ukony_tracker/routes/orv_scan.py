"""Session-authenticated ORV fragment and one-photo endpoint."""
import logging
import os
import time
import uuid

from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import db
from services import orv_images, orv_scan_service
from services.vehicle_fill_service import transaction

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
    return render_template("_orv_sken.html"), 200, {"Cache-Control": "no-store"}


@bp.post("/ukony/orv-sken")
def scan():
    start = time.monotonic()
    result = {"stav": "chyba", "ukon": None}
    orv_scan_service.tokens.set(0)
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
        result = orv_scan_service.zpracuj(conn, image_bytes, media_type)
        return jsonify(result)
    except RequestEntityTooLarge:
        return jsonify(error="Fotka smí mít nejvýše 8 MB."), 413
    except (ValueError, BadRequest) as exc:
        return jsonify(error=str(exc) if isinstance(exc, ValueError) else "Neplatné nahrání fotky."), 400
    except Exception:
        return jsonify(error="Fotku se nepodařilo zpracovat. Zkuste to znovu."), 500
    finally:
        logger.info("stav=%s ukon=%s ms=%d tokens=%d", result["stav"],
                    (result.get("ukon") or {}).get("id", "-"),
                    round((time.monotonic() - start) * 1000), orv_scan_service.tokens.get())
