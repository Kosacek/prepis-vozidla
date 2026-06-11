import json
from datetime import date

from flask import Blueprint, render_template, request

import db
from repositories import ukony_repo
from services import stats_service as st

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    conn = db.get_db()
    today = date.today()

    # Year selector scopes the charts/breakdowns; the KPI row always shows "now".
    roky = [int(r["y"]) for r in conn.execute(
        "SELECT DISTINCT substr(datum,1,4) y FROM ukony ORDER BY y DESC")]
    if today.year not in roky:
        roky.insert(0, today.year)
    year = request.args.get("rok", type=int) or today.year

    # previous month (for the comparison line under "Tento měsíc")
    prev_y, prev_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    trend = st.rocni_trend(conn, year)

    return render_template(
        "dashboard.html",
        year=year,
        roky=roky,
        aktualni_rok=today.year,
        dnes=st.denni_souhrn(conn, today.isoformat()),
        mesic=st.mesicni_souhrn(conn, today.year, today.month),
        minuly_mesic=st.mesicni_souhrn(conn, prev_y, prev_m),
        rok=st.rocni_souhrn(conn, today.year),
        nezaplaceno=st.nezaplaceno_celkem(conn),
        dluhy=st.nezaplaceno_podle_firmy(conn),
        per_firma=st.podle_firmy(conn, year),
        per_typ=st.podle_typu(conn, year),
        recent=list(ukony_repo.list(conn))[:10],
        trend_json=json.dumps(
            [{"m": t["month"], "trzby": t["trzby"], "pocet": t["pocet"]} for t in trend]
        ),
    )
