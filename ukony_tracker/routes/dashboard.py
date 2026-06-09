import json
from datetime import date
from flask import Blueprint, render_template, request
import db
from services import stats_service as st
from repositories import ukony_repo

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    conn = db.get_db()
    today = date.today()
    roky = [int(r["y"]) for r in conn.execute(
        "SELECT DISTINCT substr(datum,1,4) y FROM ukony ORDER BY y DESC")]
    if today.year not in roky:
        roky.insert(0, today.year)
    year = request.args.get("rok", type=int) or today.year
    month = today.month if year == today.year else 12
    trend = st.rocni_trend(conn, year)
    per_typ = st.podle_typu(conn, year)
    recent = list(ukony_repo.list(conn))[:8]
    return render_template(
        "dashboard.html",
        year=year, month=month, roky=roky,
        mesic=st.mesicni_souhrn(conn, year, month),
        rok=st.rocni_souhrn(conn, year),
        nezaplaceno=st.nezaplaceno_celkem(conn),
        per_firma=st.podle_firmy(conn, year),
        recent=recent,
        trend_json=json.dumps([{"m": t["month"], "trzby": t["trzby"], "pocet": t["pocet"]} for t in trend]),
        typ_json=json.dumps([{"kod": r["typ_kod"], "pocet": r["pocet"], "trzby": r["trzby"]} for r in per_typ]),
    )
