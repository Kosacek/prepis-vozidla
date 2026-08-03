"""Deterministic "Zeptej se" — answers questions about the úkony data.

NO AI / LLM. The question is parsed into a structured query (období + filtry +
záměr) and every number comes straight from SQLite, so the answers are exact,
instant and free — an LLM would happily invent a total, which is unacceptable
for money data. A question we can't parse says so and offers examples instead
of guessing.

Public API: ``answer(conn, question) -> dict``.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date, timedelta

import config

# ── text helpers ──────────────────────────────────────────────────────────────


def fold(s: str | None) -> str:
    """Lowercase + strip diacritics so 'Červenec' == 'cervenec' == 'CERVENEC'."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", (s or "").lower())
        if not unicodedata.combining(ch)
    )


def _pl(n: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 úkon, 2–4 úkony, 5+ úkonů."""
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def kc(value: float | None) -> str:
    """12345.0 -> '12 345 Kč'."""
    return f"{int(round(value or 0)):,}".replace(",", " ") + " Kč"


def _ukony(n: int) -> str:
    return f"{n} {_pl(n, 'úkon', 'úkony', 'úkonů')}"


def _cz_date(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso and len(iso) >= 10 else iso


MESICE = ["leden", "únor", "březen", "duben", "květen", "červen",
          "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


def _cz_month(ym: str) -> str:
    try:
        y, m = ym.split("-")
        return f"{MESICE[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return ym


# ── období ────────────────────────────────────────────────────────────────────

# Month stems incl. common inflections ("v červnu", "za červenec"). Matched
# LONGEST-FIRST so 'cervenec' can't be swallowed by the shorter 'cerven'.
_MONTH_STEMS: list[tuple[str, int]] = sorted([
    ("leden", 1), ("lednu", 1), ("ledna", 1),
    ("unor", 2), ("unoru", 2), ("unora", 2),
    ("brezen", 3), ("breznu", 3), ("brezna", 3),
    ("duben", 4), ("dubnu", 4), ("dubna", 4),
    ("kveten", 5), ("kvetnu", 5), ("kvetna", 5),
    ("cervenec", 7), ("cervenci", 7), ("cervence", 7),
    ("cerven", 6), ("cervnu", 6), ("cervna", 6),
    ("srpen", 8), ("srpnu", 8), ("srpna", 8),
    ("zari", 9),
    ("rijen", 10), ("rijnu", 10), ("rijna", 10),
    ("listopad", 11), ("listopadu", 11),
    ("prosinec", 12), ("prosinci", 12), ("prosince", 12),
], key=lambda p: -len(p[0]))


def _month_range(year: int, month: int) -> tuple[str, str, str]:
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat(), f"{MESICE[month - 1]} {year}"


def parse_period(q: str, today: date | None = None) -> tuple[str | None, str | None, str]:
    """Return ``(datum_od, datum_do, popis)``. ``(None, None, 'celkem')`` means no
    period was mentioned → search everything."""
    t = today or date.today()
    f = fold(q)

    if "dnes" in f:
        return t.isoformat(), t.isoformat(), "dnes"
    if "vcera" in f:
        y = t - timedelta(days=1)
        return y.isoformat(), y.isoformat(), "včera"
    # "týden"/"měsíc" count as a PERIOD only when qualified ("tento měsíc",
    # "minulý týden"). Bare "nejlepší měsíc" is a grouping dimension — treating
    # it as the current month made that question return nothing.
    qualified = any(w in f for w in ("tento", "tenhle", "tohle", "aktualni",
                                     "minul", "predchoz"))
    if ("tyden" in f or "tydnu" in f) and qualified:
        start = t - timedelta(days=t.weekday())
        if "minul" in f or "predchoz" in f:
            start -= timedelta(days=7)
            return start.isoformat(), (start + timedelta(days=6)).isoformat(), "minulý týden"
        return start.isoformat(), t.isoformat(), "tento týden"
    if ("mesic" in f or "mesici" in f) and qualified:
        if "minul" in f or "predchoz" in f:
            y, m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
            a, b, _ = _month_range(y, m)
            return a, b, "minulý měsíc"
        a, b, _ = _month_range(t.year, t.month)
        return a, b, "tento měsíc"
    if "loni" in f or "minuly rok" in f:
        y = t.year - 1
        return f"{y}-01-01", f"{y}-12-31", str(y)
    if "letos" in f or "tento rok" in f:
        return f"{t.year}-01-01", f"{t.year}-12-31", str(t.year)

    m = re.search(r"poslednich\s+(\d{1,3})\s*(dnu|dni|dn)", f)
    if m:
        days = int(m.group(1))
        start = t - timedelta(days=days - 1)
        return start.isoformat(), t.isoformat(), f"posledních {days} dní"

    year_m = re.search(r"\b(20\d{2})\b", f)
    year = int(year_m.group(1)) if year_m else None

    for stem, month in _MONTH_STEMS:
        if stem in f:
            return _month_range(year or t.year, month)

    if year:
        return f"{year}-01-01", f"{year}-12-31", str(year)

    return None, None, "celkem"


# ── filtry ────────────────────────────────────────────────────────────────────

# Words that must never be treated as a name in the free-text fallback.
_STOP = {
    "kolik", "kolikrat", "kolikate", "co", "jak", "jake", "jaky", "jaka", "kdo",
    "kde", "kdy", "jsme", "jsem", "byl", "byla", "bylo", "byly", "mame", "mel",
    "mela", "udelali", "udelal", "udelala", "delali", "vydelali", "utrzili",
    "utrzil", "vydelal", "za", "na", "od", "do", "pro", "ve", "se", "po", "pri",
    "nebo", "the", "and", "ukon", "ukonu", "ukony", "ukonech", "penez", "penize",
    "korun", "trzby", "trzeb", "obrat", "celkem", "vsech", "vsechny", "nejlepsi",
    "nejhorsi", "nejvic", "nejmene", "nejmin", "top", "den", "dne", "dni", "dnu",
    "mesic", "mesici", "mesicu", "tyden", "tydnu", "rok", "roce", "roku", "firma",
    "firmy", "firmu", "firem", "typ", "typu", "typy", "auto", "aut", "auta",
    "vozidlo", "vozidel", "prace", "praci", "nam", "tento", "tenhle", "minuly",
    "letos", "loni", "dnes", "vcera", "posledni", "poslednich", "zaplaceno",
    "nezaplaceno", "prumerne", "prumer", "bylo", "kus", "kusu", "nejcastejsi",
}
# Period words are consumed by parse_period — they must never be mistaken for a
# person's name in the free-text fallback ("za červenec" is not a customer).
_STOP |= {stem for stem, _ in _MONTH_STEMS}


def _match_firma(conn: sqlite3.Connection, f: str):
    """Longest firm name mentioned in the question, or None."""
    best = None
    for row in conn.execute("SELECT id, zkratka, nazev FROM firmy"):
        for cand in (row["zkratka"], row["nazev"]):
            c = fold(cand).strip()
            if len(c) >= 3 and c in f and (best is None or len(c) > best[1]):
                best = (row, len(c))
    return best[0] if best else None


def _match_osoba(f: str) -> str | None:
    for p in config.PROFILY:
        if fold(p) in f:
            return p
    return None


def _match_typ(conn: sqlite3.Connection, f: str) -> str | None:
    best = None
    for row in conn.execute("SELECT kod FROM typy_ukonu"):
        c = fold(row["kod"])
        if len(c) >= 3 and c in f and (best is None or len(c) > len(best)):
            best = row["kod"]
    return best


def _leftover_terms(f: str) -> list[str]:
    """Name-ish words the parser didn't consume — feeds the free-text search
    ('kolik práce od Radima Vyškova')."""
    return [w for w in re.findall(r"[a-z0-9]{3,}", f) if w not in _STOP][:3]


# ── SQL ───────────────────────────────────────────────────────────────────────

_FIRMA_JOIN = " JOIN firmy f ON f.id = u.firma_id"


def _filters(od, do, firma=None, osoba=None, typ=None, stav=None):
    where, args = [], []
    if od:
        where.append("u.datum >= ?")
        args.append(od)
    if do:
        where.append("u.datum <= ?")
        args.append(do)
    if firma is not None:
        where.append("u.firma_id = ?")
        args.append(firma["id"])
    if osoba:
        where.append("u.zpracoval = ?")
        args.append(osoba)
    if typ:
        where.append("u.typ_kod = ?")
        args.append(typ)
    if stav:
        where.append("u.stav_platby = ?")
        args.append(stav)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def _totals(conn, clause, args) -> tuple[int, float]:
    r = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(u.celkem),0) kc FROM ukony u{clause}", args
    ).fetchone()
    return r["n"], r["kc"]


def _group(conn, clause, args, expr, join="", limit=8):
    return conn.execute(
        f"SELECT {expr} AS label, COUNT(*) n, COALESCE(SUM(u.celkem),0) kc"
        f" FROM ukony u{join}{clause} GROUP BY label"
        f" ORDER BY kc DESC LIMIT {int(limit)}",
        args,
    ).fetchall()


def _text_totals(conn, od, do, term: str) -> tuple[int, float]:
    """Count+sum of úkony whose poznámka / převod / RZ / VIN contains `term`.

    Folded in Python, not SQL LIKE: SQLite's LIKE is diacritic-sensitive, so
    'vyskov' would never match the stored 'VYŠKOV'."""
    clause, args = _filters(od, do)
    t = fold(term)
    # Czech declension: the question says "od Radima Vyškova", the note stores
    # "RADIM VYŠKOV" — so also try the stem with 1–2 trailing letters dropped.
    stems = [t] + [t[:-1]] * (len(t) >= 5) + [t[:-2]] * (len(t) >= 6)
    n, total = 0, 0.0
    for r in conn.execute(
        "SELECT u.poznamka, u.prevod, u.rz, u.vin, u.celkem FROM ukony u" + clause, args
    ):
        hay = fold(" ".join(x for x in (r["poznamka"], r["prevod"], r["rz"], r["vin"]) if x))
        if any(s in hay for s in stems):
            n += 1
            total += r["celkem"] or 0
    return n, total


# ── hlavní vstup ──────────────────────────────────────────────────────────────


def answer(conn: sqlite3.Connection, question: str, today: date | None = None) -> dict:
    """Answer a Czech question about the úkony. Returns::

        {"understood": bool, "headline": str, "detail": str|None,
         "rows": [{"label","n","kc"}], "period": str, "filters": [str]}
    """
    q = (question or "").strip()
    if not q:
        return {"understood": False, "headline": "", "detail": None, "rows": [],
                "period": "", "filters": []}

    f = fold(q)
    od, do, period = parse_period(q, today)
    firma = _match_firma(conn, f)
    osoba = _match_osoba(f)
    typ = _match_typ(conn, f)
    stav = "nezaplaceno" if ("nezaplac" in f or "dluh" in f or "dluzi" in f) else None

    filters = []
    if firma is not None:
        filters.append(firma["zkratka"])
    if osoba:
        filters.append(osoba)
    if typ:
        filters.append(typ)
    if stav:
        filters.append("nezaplacené")

    wants_money = any(w in f for w in ("penez", "penize", "korun", " kc", "trzb",
                                       "obrat", "vydelal", "utrzil"))
    superlative = any(w in f for w in ("nejlepsi", "nejvic", "top", "rekord",
                                       "nejhorsi", "nejmin", "nejmene", "nejcastejsi"))

    clause, args = _filters(od, do, firma, osoba, typ, stav)
    obdobi = "" if period == "celkem" else f" ({period})"

    # 1) nejlepší den / měsíc
    if superlative and any(w in f for w in ("den", "dne", "dni", "dnu")):
        rows = _group(conn, clause, args, "u.datum", limit=5)
        if not rows:
            return _empty(period, filters)
        top = rows[0]
        return _ok(f"Nejlepší den{obdobi}: {_cz_date(top['label'])} — "
                   f"{_ukony(top['n'])} za {kc(top['kc'])}",
                   "Další nejsilnější dny:",
                   [{"label": _cz_date(r["label"]), "n": r["n"], "kc": r["kc"]} for r in rows[1:]],
                   period, filters)

    if superlative and ("mesic" in f or "mesici" in f or "mesicu" in f):
        rows = _group(conn, clause, args, "substr(u.datum,1,7)", limit=6)
        if not rows:
            return _empty(period, filters)
        top = rows[0]
        return _ok(f"Nejlepší měsíc: {_cz_month(top['label'])} — "
                   f"{_ukony(top['n'])} za {kc(top['kc'])}",
                   "Ostatní měsíce:",
                   [{"label": _cz_month(r["label"]), "n": r["n"], "kc": r["kc"]} for r in rows[1:]],
                   period, filters)

    # 2) podle firmy
    if "firm" in f and firma is None:
        rows = _group(conn, clause, args, "f.zkratka", _FIRMA_JOIN)
        if not rows:
            return _empty(period, filters)
        top = rows[0]
        return _ok(f"Nejvíc{obdobi}: {top['label']} — {_ukony(top['n'])} za {kc(top['kc'])}",
                   "Podle firmy:",
                   [{"label": r["label"], "n": r["n"], "kc": r["kc"]} for r in rows],
                   period, filters)

    # 3) podle člověka
    if ("kdo" in f or "podle koho" in f) and not osoba:
        # Only real people: most older úkony have no `zpracoval`, and an unnamed
        # bucket winning the ranking answers nothing.
        osoba_clause = clause + (" AND " if clause else " WHERE ") + \
            "u.zpracoval IS NOT NULL AND TRIM(u.zpracoval) <> ''"
        rows = _group(conn, osoba_clause, args, "u.zpracoval")
        if not rows:
            return _empty(period, filters)
        top = rows[0]
        return _ok(f"Nejvíc{obdobi} udělal {top['label']} — "
                   f"{_ukony(top['n'])} za {kc(top['kc'])}",
                   "Podle člověka:",
                   [{"label": r["label"], "n": r["n"], "kc": r["kc"]} for r in rows],
                   period, filters)

    # 4) podle typu
    if "typ" in f and not typ:
        rows = _group(conn, clause, args, "u.typ_kod")
        if not rows:
            return _empty(period, filters)
        top = rows[0]
        return _ok(f"Nejčastější typ{obdobi}: {top['label']} — "
                   f"{_ukony(top['n'])} za {kc(top['kc'])}",
                   "Podle typu úkonu:",
                   [{"label": r["label"], "n": r["n"], "kc": r["kc"]} for r in rows],
                   period, filters)

    # 5) volný text — jméno protistrany, RZ, VIN ("kolik práce od Radima Vyškova").
    # MUSÍ být před součtem: jinak by dotaz se slovem „kolik" spadl do celkového
    # součtu a jméno by se ignorovalo.
    if firma is None and not osoba and not typ and not stav:
        terms = _leftover_terms(f)
        if terms:
            alt = _fallback_text(conn, terms, od, do, period)
            if alt["understood"]:
                return alt

    # 6) prostý součet (s filtry) — nejčastější dotaz
    if firma is not None or osoba or typ or stav or period != "celkem" or "kolik" in f:
        n, total = _totals(conn, clause, args)
        popis = ", ".join(filters)
        kdo = f" — {popis}" if popis else ""
        headline = (f"{kc(total)} za {_ukony(n)}{obdobi}{kdo}" if wants_money
                    else f"{_ukony(n)} za {kc(total)}{obdobi}{kdo}")
        rows = []
        if n and firma is None and not osoba:
            rows = [{"label": r["label"], "n": r["n"], "kc": r["kc"]}
                    for r in _group(conn, clause, args, "f.zkratka", _FIRMA_JOIN, limit=6)]
        return _ok(headline, "Podle firmy:" if rows else None, rows, period, filters)

    return _fallback_text(conn, [], od, do, period)


def _ok(headline, detail, rows, period, filters) -> dict:
    return {"understood": True, "headline": headline, "detail": detail,
            "rows": rows, "period": period, "filters": filters}


def _empty(period, filters) -> dict:
    return _ok("Za tohle období nemám žádná data.", None, [], period, filters)


def _fallback_text(conn, terms, od, do, period) -> dict:
    for term in terms:
        n, total = _text_totals(conn, od, do, term)
        if n:
            obdobi = "" if period == "celkem" else f" ({period})"
            return _ok(f"„{term}“{obdobi} — {_ukony(n)} za {kc(total)}",
                       "Nalezeno v poznámce, převodu, RZ nebo VIN.",
                       [], period, [term])
    return {
        "understood": False,
        "headline": "Tomu nerozumím.",
        "detail": "Umím počty a tržby za období, firmu, člověka nebo typ, "
                  "nejlepší den/měsíc, nezaplacené a hledání jména v poznámkách. "
                  "Zkus některý z příkladů níž.",
        "rows": [], "period": period, "filters": [],
    }
