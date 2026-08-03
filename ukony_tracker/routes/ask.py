"""Zeptej se — a plain-form question box answered from SQL (no AI)."""
from flask import Blueprint, render_template, request

import db
from services import ask_service, colors_service

bp = Blueprint("ask", __name__)

# Shown as clickable chips so the box is self-teaching — these are exactly the
# question shapes the parser handles.
PRIKLADY = [
    "Kolik úkonů jsme udělali tento měsíc?",
    "Kolik peněz za červenec?",
    "Nejlepší den?",
    "Který den v týdnu máme nejvíc kusů?",
    "Kolik děláme v pondělí?",
    "Která firma nejvíc?",
    "Kdo udělal nejvíc tento měsíc?",
    "Kolik převodů letos?",
    "Kolik je nezaplaceno?",
    "Kolik pro Cardion minulý měsíc?",
]


@bp.get("/zeptej")
def ask():
    conn = db.get_db()
    q = (request.args.get("q") or "").strip()
    res = ask_service.answer(conn, q) if q else None
    return render_template(
        "zeptej.html", q=q, res=res, priklady=PRIKLADY,
        # the listed úkony are rendered with the dashboard row partial, which
        # needs the shared firm→colour map
        firma_colors=colors_service.firma_color_map(conn),
        limit=ask_service.ROW_LIMIT,
    )
