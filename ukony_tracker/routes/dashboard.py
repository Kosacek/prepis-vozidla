import calendar
import re
from datetime import date

from flask import Blueprint, render_template, request

import db
from repositories import ukony_repo
from services import stats_service as st
from services import colors_service

bp = Blueprint("dashboard", __name__)

# Czech month names (nominative) for headings and the period picker.
MESICE = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
          "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec"]
# Short names for the x axis of the whole-year trend.
MESICE_KRATKE = ["Led", "Úno", "Bře", "Dub", "Kvě", "Čvn",
                 "Čvc", "Srp", "Zář", "Říj", "Lis", "Pro"]

_OBDOBI = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2]))?$")


def parse_obdobi(raw: str | None, today: date) -> tuple[int, int | None]:
    """'2026-10' -> (2026, 10), '2026' -> (2026, None); anything else (or a
    missing value) -> the current month. Never raises."""
    m = _OBDOBI.match((raw or "").strip())
    if not m:
        return today.year, today.month
    year = int(m.group(1))
    if not 2000 <= year <= 2100:
        return today.year, today.month
    return year, int(m.group(2)) if m.group(2) else None


def obdobi_value(year: int, month: int | None) -> str:
    return f"{year:04d}-{month:02d}" if month else f"{year:04d}"


def obdobi_label(year: int, month: int | None) -> str:
    return f"{MESICE[month - 1]} {year}" if month else f"Celý rok {year}"


def period_options(conn, today: date) -> dict:
    """Months (newest first) and whole years that have data, always including
    the current month/year so the default selection exists."""
    months = {r["m"] for r in conn.execute(
        "SELECT DISTINCT substr(datum,1,7) m FROM ukony WHERE datum <> ''")}
    months.add(f"{today.year:04d}-{today.month:02d}")
    years = {m[:4] for m in months}
    return {
        "mesice": [{"value": m, "label": obdobi_label(int(m[:4]), int(m[5:7]))}
                   for m in sorted(months, reverse=True)],
        "roky": [{"value": y, "label": f"Celý rok {y}"}
                 for y in sorted(years, reverse=True)],
    }


def build_trend(conn, year: int, month: int | None, today: date) -> dict:
    """Trend data for the line/bar chart: daily for a month, monthly for a year.
    The current month/year stops at today (no trailing empty slots)."""
    if month:
        days = (today.day if (year, month) == (today.year, today.month)
                else calendar.monthrange(year, month)[1])
        rows = st.denni_trend(conn, year, month, days)
        firmy = st.denni_trend_podle_firmy(conn, year, month, days)
        return {
            "kind": "den",
            "labels": [str(r["d"]) for r in rows],
            "rows": [{"pocet": r["pocet"], "trzby": r["trzby"]} for r in rows],
            "firmy": [{"zkratka": f["zkratka"], "pocty": f["pocty"]} for f in firmy],
        }
    slots = today.month if year == today.year else 12
    rows = st.rocni_trend(conn, year)[:slots]
    firmy = st.rocni_trend_podle_firmy(conn, year)
    return {
        "kind": "mesic",
        "labels": MESICE_KRATKE[:slots],
        "rows": [{"pocet": r["pocet"], "trzby": r["trzby"]} for r in rows],
        "firmy": [{"zkratka": f["zkratka"], "pocty": f["pocty"][:slots]} for f in firmy],
    }


@bp.get("/")
def index():
    conn = db.get_db()
    today = date.today()

    # The picker (?obdobi=YYYY or YYYY-MM) scopes the trend chart and both
    # breakdown cards; the KPI row always shows "now". ?rok=YYYY is the old
    # year-only link and still works.
    raw = request.args.get("obdobi") or request.args.get("rok")
    year, month = parse_obdobi(raw, today)

    # previous month (for the comparison line under "Tento měsíc")
    prev_y, prev_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    per_firma = st.podle_firmy(conn, year, month)
    per_typ = st.podle_typu(conn, year, month)
    souhrn = st.mesicni_souhrn(conn, year, month) if month else st.rocni_souhrn(conn, year)

    # One canonical firm -> color map for both the chart and the recent list.
    firma_colors = colors_service.firma_color_map(conn)

    return render_template(
        "dashboard.html",
        year=year,
        month=month,
        obdobi=obdobi_value(year, month),
        period_label=obdobi_label(year, month),
        options=period_options(conn, today),
        souhrn=souhrn,
        firma_colors=firma_colors,
        aktualni_rok=today.year,
        dnes=st.denni_souhrn(conn, today.isoformat()),
        tyden=st.tydenni_souhrn(conn, today.isoformat()),
        mesic=st.mesicni_souhrn(conn, today.year, today.month),
        minuly_mesic=st.mesicni_souhrn(conn, prev_y, prev_m),
        rok=st.rocni_souhrn(conn, today.year),
        per_firma=per_firma,
        recent=ukony_repo.list(conn, limit=12),
        # Plain structures — the template serializes them with |tojson, which
        # (unlike json.dumps + |safe) escapes </script> and friends.
        trend_chart=build_trend(conn, year, month, today),
        per_firma_chart=[{"zkratka": r["zkratka"], "pocet": r["pocet"], "trzby": r["trzby"]}
                         for r in per_firma],
        per_typ_chart=[{"kod": t["typ_kod"], "pocet": t["pocet"], "trzby": t["trzby"]} for t in per_typ],
    )
