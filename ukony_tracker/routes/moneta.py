"""Nespárované platby z banky (jen když je nastaven MONETA_API_TOKEN)."""
from flask import Blueprint, abort, render_template

import db
from services import moneta_client

bp = Blueprint("moneta", __name__)


@bp.get("/doklady/platby")
def platby():
    if not moneta_client.enabled():
        abort(404)
    rows = db.get_db().execute(
        "SELECT * FROM moneta_platby WHERE stav='nesparovano' ORDER BY datum DESC, id DESC").fetchall()
    return render_template("moneta_platby.html", platby=rows)
