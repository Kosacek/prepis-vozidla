"""Server-rendered question page with a read-only AI planner and SQL fallback."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import closing
from datetime import date

from flask import Blueprint, jsonify, render_template, request, session

import config
import db
from services import ai_assistant, ai_tools, ask_service, colors_service

bp = Blueprint("ask", __name__)
logger = logging.getLogger("zeptej")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
_rate_lock = threading.Lock()
_rate: dict[str, list[float]] = {}
_metric_names = {"pocet": "počet úkonů", "soucet_kc": "součet Kč",
                 "prumer_kc": "průměr Kč", "nezaplaceno_kc": "nezaplaceno Kč",
                 "zaplaceno_kc": "zaplaceno Kč"}
_group_names = {"den_v_tydnu": "den v týdnu", "den": "den", "tyden": "týden",
                "mesic": "měsíc", "firma": "firma", "typ": "typ úkonu",
                "zpracoval": "zpracoval", "stav_platby": "stav platby"}
_filter_names = {"firma_ids": "firmy", "typy": "typy", "zpracoval": "lidé",
                 "stav_platby": "stav platby", "dny_v_tydnu": "dny v týdnu",
                 "poznamka_obsahuje": "poznámka obsahuje", "bez_rz": "bez RZ"}

PRIKLADY = [
    "Kolik jsme vydělali tento měsíc?",
    "Kdo dělá víc, Roman nebo David?",
    "Průměr podle dne v týdnu na grafu",
    "Co nám kdo dluží?",
    "Kolik PPD jsme vystavili v září?",
    "Kdy bylo nejvíc práce?",
    "Kolik bylo elektrických značek?",
    "Ukaž poslední úkony od Romana",
]


def _rate_allowed() -> bool:
    sid = session.get("zeptej_sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["zeptej_sid"] = sid
    now = time.monotonic()
    with _rate_lock:
        recent = [stamp for stamp in _rate.get(sid, []) if now - stamp < 600]
        if len(recent) >= 30:
            _rate[sid] = recent
            return False
        recent.append(now)
        _rate[sid] = recent
        return True


def _explanation(ai: dict) -> dict:
    result = ai.get("vysledek") or {}
    last = ai.get("volani", [])[-1] if ai.get("volani") else {}
    params = last.get("input") or {}
    period = result.get("obdobi") or params.get("obdobi") or {}
    filters = result.get("pouzite_filtry") or params.get("filtry") or {}
    if ai.get("nastroj") == "doklady_ppd" and params.get("hledat"):
        filters = {"hledat": params["hledat"]}
    metric = _metric_names.get(params.get("metrika"), "příjmové pokladní doklady" if ai.get("nastroj") == "doklady_ppd" else "seznam úkonů")
    if params.get("prumer_na"):
        metric += " na " + _group_names.get(params["prumer_na"], params["prumer_na"])
    return {
        "obdobi": f"{period.get('od', '—')} až {period.get('do', '—')}",
        "metrika": metric,
        "skupiny": ", ".join(_group_names.get(g, g) for g in params.get("skupiny", [])) or "bez rozdělení",
        "filtry": "; ".join(f"{_filter_names.get(key, key)}: {', '.join(map(str, value)) if isinstance(value, list) else value}"
                            for key, value in filters.items()) or "žádné",
        "predpoklady": ai.get("predpoklady", "") if ai_assistant.verify_sentence(
            ai.get("predpoklady", ""), [result] if result else []) else "",
    }


def _listed_ukony(ai: dict):
    result = ai.get("vysledek") or {}
    if ai.get("nastroj") != "seznam_ukonu" or not result.get("radky"):
        return []
    period = result["obdobi"]
    with closing(ai_tools.connect_ro(config.DB_PATH)) as conn:
        start, end = date.fromisoformat(period["od"]), date.fromisoformat(period["do"])
        clause, args = ai_tools._sql_filters(conn, start, end, result.get("pouzite_filtry") or {})
        return conn.execute(
            "SELECT u.*, f.zkratka AS firma_zkratka FROM ukony u "
            "JOIN firmy f ON f.id=u.firma_id" + clause +
            " ORDER BY u.datum DESC, u.id DESC LIMIT ?",
            [*args, len(result["radky"])],
        ).fetchall()


def _odpoved(conn, q: str, historie=None) -> dict:
    """Jedno kolo „Zeptej se": AI (s historií konverzace), jinak pravidlový parser."""
    ai = None
    res = None
    fallback_reason = None
    rows = []
    explanation = None
    started = time.monotonic()
    if request.args.get("rezim") == "jednoduchy":
        fallback_reason = "vyžádaný jednoduchý režim"
    elif not _rate_allowed():
        fallback_reason = "limit 30 dotazů za 10 minut"
    else:
        try:
            ai = ai_assistant.ask(q, db_path=config.DB_PATH, today=date.today(), historie=historie)
            rows = _listed_ukony(ai)
            explanation = _explanation(ai)
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"
            ai = None
    if fallback_reason:
        res = ask_service.answer(conn, q)
    logger.info("%s", json.dumps({
        "otazka": q, "historie": len(historie or []), "volani": (ai or {}).get("volani", []),
        "tokeny": (ai or {}).get("tokeny", {}),
        "ms": (ai or {}).get("ms", round((time.monotonic() - started) * 1000)),
        "veta_overena": (ai or {}).get("veta_overena", False),
        "fallback": fallback_reason,
    }, ensure_ascii=False, default=str))
    return {"q": q, "ai": ai, "res": res, "fallback_reason": fallback_reason,
            "explanation": explanation, "ai_rows": rows}


def _shrnuti(kolo: dict) -> str:
    """Co si prohlížeč pošle zpátky jako historii: věta + jak byla spočítaná,
    aby „a v září?" mohlo převzít období, filtry i metriku."""
    ai, res = kolo["ai"], kolo["res"]
    if ai and ai.get("typ") == "doptat_se":
        moznosti = " | ".join(ai.get("moznosti") or [])
        return (ai.get("otazka") or "") + (f" Možnosti: {moznosti}" if moznosti else "")
    if ai:
        veta = ai.get("veta") if ai.get("veta_overena") else ""
        e = kolo.get("explanation") or {}
        jak = (f"Nástroj {ai.get('nastroj')}; období {e.get('obdobi', '—')}; metrika {e.get('metrika', '—')}; "
               f"skupiny {e.get('skupiny', '—')}; filtry {e.get('filtry', '—')}.")
        return f"{veta} [{jak}]".strip()
    return (res or {}).get("headline", "") if isinstance(res, dict) else getattr(res, "headline", "")


def _kontext_kola(conn) -> dict:
    return {"firma_colors": colors_service.firma_color_map(conn), "limit": ask_service.ROW_LIMIT}


@bp.get("/zeptej")
def ask():
    conn = db.get_db()
    q = (request.args.get("q") or "").strip()[:300]
    kolo = _odpoved(conn, q) if q else None
    return render_template(
        "zeptej.html", q=q, kolo=kolo, shrnuti=_shrnuti(kolo) if kolo else "",
        priklady=PRIKLADY, **_kontext_kola(conn),
    )


@bp.post("/zeptej/kolo")
def kolo():
    """Další kolo konverzace: tělo {q, historie:[{q, a}]} → HTML odpovědi + shrnutí.

    POST jen kvůli historii v těle (do URL by se nevešla); nic nezapisuje, proto
    je vyjmutý z automatické zálohy v app.py."""
    conn = db.get_db()
    telo = request.get_json(silent=True)
    telo = telo if isinstance(telo, dict) else {}
    q = str(telo.get("q") or "").strip()[:300]
    if not q:
        return jsonify(error="prázdný dotaz"), 400
    kolo_ = _odpoved(conn, q, telo.get("historie"))
    html = render_template("_zeptej_kolo.html", **kolo_, **_kontext_kola(conn))
    return jsonify(html=html, shrnuti=_shrnuti(kolo_))
