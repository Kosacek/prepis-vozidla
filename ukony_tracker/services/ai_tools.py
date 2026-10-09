"""Read-only query tools. SQLite computes metrics; no model or free-form SQL."""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from services.ask_service import _cz_month, _filters, fold
from repositories import ppd_repo

METRIKY = ("pocet", "soucet_kc", "prumer_kc", "nezaplaceno_kc", "zaplaceno_kc")
SKUPINY = ("den_v_tydnu", "den", "tyden", "mesic", "firma", "typ",
           "zpracoval", "stav_platby")
PRUMER_NA = ("den_v_tydnu", "den", "tyden", "mesic")
LIDE = ("David", "Petr", "Roman")
STAVY = ("nezaplaceno", "castecne", "zaplaceno")
DNY = ("Po", "Út", "St", "Čt", "Pá", "So", "Ne")


def _object_schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _array_schema(items: dict) -> dict:
    return {"type": ["array", "null"], "items": items}


_OBDOBI_SCHEMA = _object_schema({
    key: {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
    for key in ("od", "do")
})
_FILTRY_SCHEMA = _object_schema({
    "firma_ids": _array_schema({"type": "integer", "minimum": 1}),
    "typy": _array_schema({"type": "string"}),
    "zpracoval": _array_schema({"type": "string", "enum": list(LIDE)}),
    "stav_platby": _array_schema({"type": "string", "enum": list(STAVY)}),
    "dny_v_tydnu": _array_schema({"type": "integer", "minimum": 1, "maximum": 7}),
    "poznamka_obsahuje": {"type": ["string", "null"]},
    "bez_rz": {"type": ["boolean", "null"]},
})
TOOLS: list[dict] = [
    {
        "name": "agregace",
        "description": (
            "Spočítá počty a peníze včetně částečných plateb za uzavřené období od–do. "
            "prumer_kc bez prumer_na je součet cen dělený počtem úkonů. "
            "prumer_na dělí počet úkonů (pocet) nebo součet příslušných peněz "
            "kalendářním dělitelem: den_v_tydnu = součet za daný den v týdnu / "
            "počet TAKOVÝCH dnů v období, včetně dnů bez úkonů, nikoli počet řádků "
            "(vyžaduje skupinu den_v_tydnu nebo filtr na jediný den v týdnu); "
            "den = počet dní včetně obou mezí; tyden / mesic = počet kalendářních "
            "ISO týdnů / měsíců, které období zasahuje, i jen částečně. "
            "Při prumer_na se i pro prumer_kc použije součet cen. "
            "Peníze zaokrouhluje na celé koruny, průměry na dvě desetinná místa. "
            "Srovnání lidí automaticky začíná společným obdobím; cele_obdobi=true "
            "toto omezení vypne. Null či prázdné pole filtru znamená bez filtru."
        ),
        "input_schema": _object_schema({
            "metrika": {"type": "string", "enum": list(METRIKY)},
            "skupiny": {"type": "array", "items": {"type": "string", "enum": list(SKUPINY)},
                        "maxItems": 2},
            "obdobi": _OBDOBI_SCHEMA,
            "filtry": _FILTRY_SCHEMA,
            "prumer_na": {"type": ["string", "null"], "enum": [None, *PRUMER_NA]},
            "jen_kde_vic_nez": {"type": ["number", "null"]},
            "cele_obdobi": {"type": "boolean"},
        }),
        "strict": True,
    },
    {
        "name": "seznam_ukonu",
        "description": (
            "Vypíše nejnovější úkony ve zvoleném období se stejnými filtry jako agregace. "
            "Limit null znamená 20, maximum je 50. VIN a poznámku vrací jen při "
            "vcetne_detailu=true. Porovnání více lidí používá společné období, "
            "pokud cele_obdobi není true."
        ),
        "input_schema": _object_schema({
            "obdobi": _OBDOBI_SCHEMA,
            "filtry": _FILTRY_SCHEMA,
            "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 50},
            "vcetne_detailu": {"type": "boolean"},
            "cele_obdobi": {"type": "boolean"},
        }),
        "strict": True,
    },
    {
        "name": "doklady_ppd",
        "description": (
            "PPD = příjmové pokladní doklady (hotovost přijatá), NE tržby z úkonů — "
            "nikdy je nesčítej s úkony. Vrátí počet a součet dokladů za období; "
            "seznam=true přidá nejvýše 20 položek. Smazané doklady se nepočítají."
        ),
        "input_schema": _object_schema({
            "obdobi": _OBDOBI_SCHEMA,
            "hledat": {"type": ["string", "null"]},
            "seznam": {"type": "boolean"},
        }),
        "strict": True,
    },
    {
        "name": "odpoved",
        "description": "Ukončí odpověď 1–2 větami česky. Použij jen čísla z výsledků nástrojů.",
        "input_schema": _object_schema({
            "veta": {"type": "string"},
            "graf": {"type": "string", "enum": ["sloupcovy", "skupinovy_sloupcovy",
                                                  "cara", "kolac", "zadny"]},
            "predpoklady": {"type": "string"},
        }),
        "strict": True,
    },
    {
        "name": "doptat_se",
        "description": "Upřesní nejasný dotaz českou otázkou a 2–3 krátkými volbami.",
        "input_schema": _object_schema({
            "otazka": {"type": "string"},
            "moznosti": {"type": "array", "items": {"type": "string"},
                         "minItems": 2, "maxItems": 3},
        }),
        "strict": True,
    },
]


_STRICT_UNSUPPORTED = ("minimum", "maximum", "minItems", "maxItems",
                       "minLength", "maxLength", "pattern")


def _strict_safe(node):
    """Copy of a schema without keywords strict tool use rejects (400).

    TOOLS keeps them as documentation; the validators below enforce each one
    server-side, so dropping them from what the API sees loses no safety. The
    YYYY-MM-DD pattern becomes the supported `format: date`.
    """
    if isinstance(node, list):
        return [_strict_safe(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _strict_safe(value) for key, value in node.items()
           if key not in _STRICT_UNSUPPORTED}
    if node.get("pattern") == r"^\d{4}-\d{2}-\d{2}$":
        out["format"] = "date"
    # A nullable enum (`type: [string, null]` + None in enum) is rejected too;
    # the accepted spelling is anyOf(string enum, null).
    if isinstance(out.get("type"), list) and None in out.get("enum", ()):
        values = [v for v in out.pop("enum") if v is not None]
        kinds = [t for t in out.pop("type") if t != "null"]
        out["anyOf"] = [{"type": kinds[0], "enum": values}, {"type": "null"}]
    return out


def _optional_filters(schema: dict) -> dict:
    """Filters as OPTIONAL non-null fields instead of required nullable ones.

    Strict schemas allow at most 16 union-typed parameters across all tools and
    the 7 nullable filters, used by two tools, alone are 14. "Missing" and
    "null" mean the same to _validated_filters, so nothing changes semantically.
    """
    props = {}
    for key, prop in schema["properties"].items():
        prop = dict(prop)
        if isinstance(prop.get("type"), list):
            prop["type"] = next(t for t in prop["type"] if t != "null")
        props[key] = prop
    return {**schema, "properties": props, "required": []}


PRUMER_ZADNY = "zadny"


def _api_tool(tool: dict) -> dict:
    safe = _strict_safe(tool)
    props = safe["input_schema"]["properties"]
    if "filtry" in props:
        props["filtry"] = _optional_filters(props["filtry"])
    if "prumer_na" in props:
        # Haiku sent the nullable anyOf as a quoted string ("\"den_v_tydnu\"");
        # a plain enum with an explicit "zadny" is unambiguous. The assistant
        # maps "zadny" back to None (see from_api_input).
        props["prumer_na"] = {"type": "string", "enum": [PRUMER_ZADNY, *PRUMER_NA]}
    return safe


def from_api_input(params: dict) -> dict:
    """Undo the API-only schema spellings before the validators see the input."""
    if not isinstance(params, dict):
        return params
    out = dict(params)
    if out.get("prumer_na") == PRUMER_ZADNY:
        out["prumer_na"] = None
    return out


API_TOOLS: list[dict] = [_api_tool(tool) for tool in TOOLS]


def connect_ro(db_path) -> sqlite3.Connection:
    """Open an existing file, escaping URI characters (also on Windows)."""
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _object(value, name: str, allowed) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} musí být objekt.")
    if any(key not in allowed for key in value):
        raise ValueError(f"{name} obsahuje neznámý parametr.")
    return value


def _enum(value, choices, name: str):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Neplatná hodnota pro {name}.")
    return value


def _boolean(params: dict, key: str) -> bool:
    value = params.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} musí být pravda nebo nepravda.")
    return value


def _period(params: dict) -> tuple[date, date]:
    period = _object(params.get("obdobi"), "Období", ("od", "do"))
    dates = []
    for key in ("od", "do"):
        value = period.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Datum musí mít tvar YYYY-MM-DD.")
        try:
            dates.append(date.fromisoformat(value))
        except ValueError as exc:
            raise ValueError("Období obsahuje neplatné datum.") from exc
    if dates[0] > dates[1]:
        raise ValueError("Začátek období nesmí být po jeho konci.")
    return dates[0], dates[1]


def _validated_filters(params: dict) -> dict:
    filters = _object(params.get("filtry", {}), "Filtry", _FILTRY_SCHEMA["properties"])
    used = {}
    for key, value in filters.items():
        if value is None:
            continue
        if key in ("firma_ids", "typy", "zpracoval", "stav_platby", "dny_v_tydnu"):
            if not isinstance(value, list):
                raise ValueError(f"Filtr {key} musí být seznam.")
            for item in value:
                if key in ("firma_ids", "dny_v_tydnu"):
                    if type(item) is not int or item < 1 or (key == "dny_v_tydnu" and item > 7):
                        raise ValueError(f"Filtr {key} obsahuje neplatné číslo.")
                elif key == "typy":
                    if not isinstance(item, str) or not item.strip():
                        raise ValueError("Filtr typy obsahuje neplatný typ úkonu.")
                else:
                    _enum(item, LIDE if key == "zpracoval" else STAVY, key)
            value = list(dict.fromkeys(value))
        elif key == "poznamka_obsahuje":
            if not isinstance(value, str):
                raise ValueError("Filtr poznamka_obsahuje musí být text.")
        elif not isinstance(value, bool):
            raise ValueError("Filtr bez_rz musí být pravda nebo nepravda.")
        if value:
            used[key] = value
    return used


def _common_period(conn, start: date, end: date, groups: list, filters: dict,
                   whole: bool) -> tuple[date, str | None]:
    people = filters.get("zpracoval", [])
    if whole or ("zpracoval" not in groups and len(people) < 2):
        return start, None
    compared = people or list(LIDE)
    marks = ",".join("?" for _ in compared)
    tracked = conn.execute(
        f"SELECT zpracoval, MIN(datum) od FROM ukony WHERE zpracoval IN ({marks})"
        " GROUP BY zpracoval ORDER BY od DESC, zpracoval", compared,
    ).fetchall()
    if not tracked or tracked[0]["od"] <= start.isoformat():
        return start, None
    since = date.fromisoformat(tracked[0]["od"])
    names = " a ".join(row["zpracoval"] for row in tracked if row["od"] == since.isoformat())
    warning = (f"{names} se v evidenci zapisuje až od {since.day}. {since.month}., "
               "srovnávám od tohoto data.")
    if since > end:
        warning += " Ve zvoleném období není společné období pro srovnání."
    return since, warning


def _sql_filters(conn, start: date, end: date, filters: dict):
    clause, args = _filters(start.isoformat(), end.isoformat())
    columns = {"firma_ids": "u.firma_id", "typy": "u.typ_kod", "zpracoval": "u.zpracoval",
               "stav_platby": "u.stav_platby",
               "dny_v_tydnu": "((CAST(strftime('%w', u.datum) AS INTEGER) + 6) % 7 + 1)"}
    for key, column in columns.items():
        if key in filters:
            values = filters[key]
            clause += f" AND {column} IN ({','.join('?' for _ in values)})"
            args.extend(values)
    if "poznamka_obsahuje" in filters:
        conn.create_function("ai_fold", 1, fold, deterministic=True)
        clause += " AND instr(ai_fold(u.poznamka), ?) > 0"
        args.append(fold(filters["poznamka_obsahuje"]))
    if filters.get("bez_rz"):
        clause += " AND TRIM(COALESCE(u.rz, ''), char(9) || char(10) || char(13) || ' ') = ''"
    return clause, args


def _metadata(conn, start: date, end: date, warning, filters: dict) -> dict:
    # Attribution coverage is for the final period, even when a people filter
    # necessarily excludes these rows from the requested metric.
    clause, args = _filters(start.isoformat(), end.isoformat())
    missing = conn.execute(
        "SELECT COUNT(*) FROM ukony u" + clause + " AND u.zpracoval IS NULL", args,
    ).fetchone()[0]
    return {"obdobi": {"od": start.isoformat(), "do": end.isoformat()},
            "upozorneni": warning, "bez_zpracovatele": missing, "pouzite_filtry": filters}


_WEEKDAY = "((CAST(strftime('%w', u.datum) AS INTEGER) + 6) % 7)"
_GROUP_SQL = {
    "den_v_tydnu": _WEEKDAY,
    "den": "u.datum",
    "tyden": "date(u.datum, '-6 days', 'weekday 1')",
    "mesic": "substr(u.datum, 1, 7)",
    "firma": "f.zkratka",
    "typ": "u.typ_kod",
    "zpracoval": "COALESCE(u.zpracoval, 'nevyplněno')",
    "stav_platby": "u.stav_platby",
}
# The schema stores REAL; convert each amount to integer haléře BEFORE summing
# or subtracting, so accumulated binary floating-point error cannot lose a Kč.
_CENA = "CAST(ROUND(COALESCE(u.celkem, 0) * 100) AS INTEGER)"
_PAID = "CAST(ROUND(COALESCE(u.zaplaceno_kc, 0) * 100) AS INTEGER)"
_METRIC_SQL = {
    "pocet": "COUNT(*)",
    "soucet_kc": f"COALESCE(SUM({_CENA}), 0)",
    "prumer_kc": f"COALESCE(SUM({_CENA}), 0)",
    "nezaplaceno_kc": f"COALESCE(SUM({_CENA} - {_PAID}), 0)",
    "zaplaceno_kc": f"COALESCE(SUM({_PAID}), 0)",
}


def _divisor(start: date, end: date, unit: str, groups: list, filters: dict):
    """Calendar denominators are independent of rows and of other filters."""
    days = max(0, (end - start).days + 1)
    if unit == "den_v_tydnu":
        counts = [days // 7 + int((dow - start.weekday()) % 7 < days % 7)
                  for dow in range(7)]
        if "den_v_tydnu" in groups:
            return f"CASE {_WEEKDAY} " + " ".join(f"WHEN {dow} THEN ?" for dow in range(7)) + " END", counts
        selected = filters.get("dny_v_tydnu", [])
        if len(selected) != 1:
            raise ValueError("Průměr na den v týdnu vyžaduje skupinu nebo filtr na jediný den v týdnu.")
        return "?", [counts[selected[0] - 1]]
    if unit == "den":
        count = days
    elif unit == "mesic":
        count = (end.year - start.year) * 12 + end.month - start.month + 1 if days else 0
    else:
        first = start - timedelta(days=start.weekday())
        last = end - timedelta(days=end.weekday())
        count = (last - first).days // 7 + 1 if days else 0
    return "?", [count]


def agregace(conn: sqlite3.Connection, params: dict, today: date) -> dict:
    params = _object(params, "Parametry", TOOLS[0]["input_schema"]["properties"])
    metric = _enum(params.get("metrika"), METRIKY, "metrika")
    groups = params.get("skupiny", [])
    if not isinstance(groups, list) or len(groups) > 2:
        raise ValueError("Skupiny musí být seznam nejvýše dvou skupin.")
    for group in groups:
        _enum(group, SKUPINY, "skupina")
    if len(set(groups)) != len(groups):
        raise ValueError("Skupiny se nesmí opakovat.")
    unit = params.get("prumer_na")
    if unit is not None:
        _enum(unit, PRUMER_NA, "prumer_na")
    threshold = params.get("jen_kde_vic_nez")
    if threshold is not None and (type(threshold) not in (int, float) or not math.isfinite(threshold)):
        raise ValueError("Mez jen_kde_vic_nez musí být konečné číslo.")
    start, end = _period(params)
    filters = _validated_filters(params)
    start, warning = _common_period(conn, start, end, groups, filters, _boolean(params, "cele_obdobi"))
    clause, args = _sql_filters(conn, start, end, filters)
    base = _METRIC_SQL[metric]
    scale = 1 if metric == "pocet" else 100
    select_args = []
    if unit is not None:
        divisor, select_args = _divisor(start, end, unit, groups, filters)
        value = f"COALESCE(ROUND(1.0 * ({base}) / NULLIF(({divisor}) * {scale}, 0), 2), 0.0)"
    elif metric == "prumer_kc":
        value = f"COALESCE(ROUND(1.0 * ({base}) / NULLIF(COUNT(*) * 100, 0), 2), 0.0)"
    elif metric == "pocet":
        value = base
    else:
        value = f"CAST(ROUND(1.0 * ({base}) / 100, 0) AS INTEGER)"
    labels = [f"{_GROUP_SQL[group]} AS g{i}" for i, group in enumerate(groups)]
    sql = "SELECT " + ", ".join([*labels, f"{value} AS hodnota", "COUNT(*) AS pocet"])
    sql += " FROM ukony u" + (" JOIN firmy f ON f.id = u.firma_id" if "firma" in groups else "") + clause
    if groups:
        sql += " GROUP BY " + ", ".join("f.id" if group == "firma" else f"g{i}"
                                        for i, group in enumerate(groups))
    sql = "SELECT * FROM (" + sql + ")"
    bindings = select_args + args
    if threshold is not None:
        sql += " WHERE hodnota > ?"
        bindings.append(threshold)
    if groups:
        sql += " ORDER BY " + ", ".join(f"g{i}" for i in range(len(groups)))
    rows = []
    for row in conn.execute(sql, bindings):
        labels = []
        for i, group in enumerate(groups):
            label = row[f"g{i}"]
            if group == "den_v_tydnu":
                label = DNY[label]
            elif group == "mesic":
                label = _cz_month(label)
            elif group == "stav_platby" and label == "castecne":
                label = "částečně zaplaceno"
            labels.append(label)
        rows.append({"skupina": labels, "hodnota": row["hodnota"], "pocet": row["pocet"]})
    result = {"radky": rows, "metrika": metric, "pocet_radku": len(rows)}
    # Totals across the shown rows, so the model quotes a DB number instead of
    # adding up the rows itself (averages don't add up, so none for those).
    if groups and unit is None and metric != "prumer_kc":
        result["celkem"] = {"hodnota": sum(r["hodnota"] for r in rows),
                            "pocet": sum(r["pocet"] for r in rows)}
    return {**result, **_metadata(conn, start, end, warning, filters)}


def seznam_ukonu(conn: sqlite3.Connection, params: dict, today: date) -> dict:
    params = _object(params, "Parametry", TOOLS[1]["input_schema"]["properties"])
    start, end = _period(params)
    filters = _validated_filters(params)
    limit = params.get("limit")
    if limit is None:
        limit = 20
    if type(limit) is not int or limit < 1:
        raise ValueError("Limit musí být kladné celé číslo.")
    limit = min(limit, 50)
    details = _boolean(params, "vcetne_detailu")
    start, warning = _common_period(conn, start, end, [], filters, _boolean(params, "cele_obdobi"))
    clause, args = _sql_filters(conn, start, end, filters)
    sql = ("SELECT u.datum, f.zkratka AS firma, u.typ_kod AS typ, u.rz, "
           "CAST(ROUND(u.celkem, 0) AS INTEGER) AS celkem, u.stav_platby, u.zpracoval")
    if details:
        sql += ", u.vin, u.poznamka"
    # Same join, newest-first order and bound LIMIT as ask_service._rows.
    sql += (" FROM ukony u JOIN firmy f ON f.id = u.firma_id" + clause
            + " ORDER BY u.datum DESC, u.id DESC LIMIT ?")
    rows = [dict(row) for row in conn.execute(sql, [*args, limit])]
    return {"radky": rows, **_metadata(conn, start, end, warning, filters)}


def doklady_ppd(conn: sqlite3.Connection, params: dict, today: date) -> dict:
    params = _object(params, "Parametry", TOOLS[2]["input_schema"]["properties"])
    start, end = _period(params)
    search = params.get("hledat")
    if search is not None and not isinstance(search, str):
        raise ValueError("Hledat musí být text nebo prázdné.")
    show_list = params.get("seznam", False)
    if not isinstance(show_list, bool):
        raise ValueError("Seznam musí být pravda nebo nepravda.")
    period = {"od": start.isoformat(), "do": end.isoformat()}
    totals = ppd_repo.totals(conn, period["od"], period["do"], q=search,
                             include_deleted=False)
    result = {"pocet": totals["pocet"], "soucet_kc": totals["castka"], "obdobi": period}
    if show_list:
        fields = ("cislo", "datum", "prijato_od", "castka", "ucel", "vozidlo")
        result["polozky"] = [{key: row[key] for key in fields} for row in ppd_repo.list(
            conn, period["od"], period["do"], q=search,
            include_deleted=False, limit=20)]
    return result


def ciselniky(conn: sqlite3.Connection, today: date) -> dict:
    period = conn.execute("SELECT MIN(datum) od, MAX(datum) do FROM ukony").fetchone()
    return {
        "firmy": [dict(row) for row in conn.execute("SELECT id, zkratka, ico FROM firmy ORDER BY zkratka, id")],
        "typy": [row[0] for row in conn.execute(
            "SELECT kod FROM typy_ukonu UNION SELECT typ_kod FROM ukony ORDER BY kod")],
        "lide": list(LIDE),
        "obdobi": dict(period),
        "dnes": today.isoformat(),
    }
