import json
from datetime import date

from flask import Blueprint, render_template, request

import db
from repositories import ukony_repo
from services import stats_service as st
from services import colors_service

bp = Blueprint("dashboard", __name__)

# Czech month names (nominative) for the chart heading.
MESICE = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
          "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec"]


@bp.get("/")
def index():
    conn = db.get_db()
    today = date.today()

    # Year selector scopes the breakdown cards; the KPI row and the "this month"
    # chart always show "now".
    roky = [int(r["y"]) for r in conn.execute(
        "SELECT DISTINCT substr(datum,1,4) y FROM ukony ORDER BY y DESC")]
    if today.year not in roky:
        roky.insert(0, today.year)
    year = request.args.get("rok", type=int) or today.year

    # previous month (for the comparison line under "Tento měsíc")
    prev_y, prev_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    # The trend chart runs day-by-day from the 1st of the current month to today.
    denni = st.denni_trend(conn, today.year, today.month, today.day)
    denni_firmy = st.denni_trend_podle_firmy(conn, today.year, today.month, today.day)
    per_typ = st.podle_typu(conn, year)

    # One canonical firm -> color map for both the chart and the recent list.
    firma_colors = colors_service.firma_color_map(conn)

    return render_template(
        "dashboard.html",
        year=year,
        firma_colors=firma_colors,
        firma_colors_json=json.dumps(firma_colors),
        roky=roky,
        aktualni_rok=today.year,
        mesic_nazev=MESICE[today.month - 1],
        dnes=st.denni_souhrn(conn, today.isoformat()),
        mesic=st.mesicni_souhrn(conn, today.year, today.month),
        minuly_mesic=st.mesicni_souhrn(conn, prev_y, prev_m),
        rok=st.rocni_souhrn(conn, today.year),
        nezaplaceno=st.nezaplaceno_celkem(conn),
        dluhy=st.nezaplaceno_podle_firmy(conn),
        per_firma=st.podle_firmy(conn, year),
        recent=list(ukony_repo.list(conn))[:12],
        denni_json=json.dumps(
            [{"d": t["d"], "trzby": t["trzby"], "pocet": t["pocet"]} for t in denni]
        ),
        denni_firmy_json=json.dumps(
            [{"zkratka": r["zkratka"], "pocty": r["pocty"]} for r in denni_firmy]
        ),
        per_typ_json=json.dumps(
            [{"kod": t["typ_kod"], "pocet": t["pocet"], "trzby": t["trzby"]} for t in per_typ]
        ),
    )
