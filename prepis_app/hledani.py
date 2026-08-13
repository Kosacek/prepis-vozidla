"""Deterministic history search for zadosti — "kdy jsem co dělal".

NO AI / LLM. The question is parsed into a structured query (období + filtry +
záměr) and every record comes straight from the files on disk, so answers are
exact, instant and free. An LLM would happily invent a receipt number or an
amount, which is unacceptable for money data. A question we can't parse says so
and offers examples instead of guessing.

Ported verbatim from the sister app's ``ukony_tracker/services/ask_service.py``
(diacritics folding, Czech plurals, money format, month stems) — the query layer
is new because zadosti has files + xlsx, not SQLite.

Public API:
    ``hledej(q, vystupy, doklady, firmy, today=None) -> dict``   (pure)
    ``nacti_vystupy(data_dir) -> list``                          (reads disk)
    ``zapis_vystup(data_dir, files, data)``                      (index one generate)
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta

# ── text helpers (ported from ask_service) ────────────────────────────────────


def fold(s: str | None) -> str:
    """Lowercase + strip diacritics so 'Vyškov' == 'vyskov' == 'VYSKOV'."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", (s or "").lower())
        if not unicodedata.combining(ch)
    )


def _pl(n: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 žádost, 2–4 žádosti, 5+ žádostí."""
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def kc(value: float | None) -> str:
    """12345.0 -> '12 345 Kč'."""
    return f"{int(round(value or 0)):,}".replace(",", " ") + " Kč"


def _zadosti(n: int) -> str:
    return f"{n} {_pl(n, 'žádost', 'žádosti', 'žádostí')}"


def _doklady(n: int) -> str:
    return f"{n} {_pl(n, 'doklad', 'doklady', 'dokladů')}"


def _cz_date(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso and len(iso) >= 10 else iso


MESICE = ["leden", "únor", "březen", "duben", "květen", "červen",
          "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]

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

    # Konkrétní datum: "15.7.", "15.7.2026", "15. 7. 2026"
    m = re.search(r"\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d{2})?", q)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else t.year
        try:
            d = date(year, month, day)
            return d.isoformat(), d.isoformat(), _cz_date(d.isoformat())
        except ValueError:
            pass

    year_m = re.search(r"\b(20\d{2})\b", f)
    year = int(year_m.group(1)) if year_m else None

    for stem, month in _MONTH_STEMS:
        if stem in f:
            return _month_range(year or t.year, month)

    if year:
        return f"{year}-01-01", f"{year}-12-31", str(year)

    return None, None, "celkem"


# ── výstupy: soubory na disku + index ─────────────────────────────────────────

# zmeny_ = převod, zapis_ = nové vozidlo, zmena_ = změna údajů. PPD sem NEPATŘÍ:
# ppd_<cislo>.pdf nemá v názvu datum, a doklady mají vlastní evidenci s datem,
# číslem, plátcem i částkou — hledají se přes ni, ne přes mtime souboru.
TYPY = {"zmeny": "Převod", "zapis": "Nové vozidlo", "zmena": "Změna údajů",
        "3rz": "Třetí značka", "pm": "Plná moc", "vyvoz": "Vývoz"}

# Název souboru má DVA tvary a oba musí jít přečíst:
#   starý  zmeny_20260720_090000.pdf                   (do 2026-08, ~850 souborů)
#   nový   zmeny_PETR-SVOBODA_1AB2345_20260720.pdf     (+ _HHMMSS při kolizi)
# Nový nese jméno a vozidlo, aby se žádost dala ve složce najít očima podle toho,
# pro koho byla — ne podle času, který nikomu nic neřekne. Staré soubory se
# nepřejmenovávají, jen se dál čtou.
_KIND = r"(3rz|zmeny|zapis|zmena|pm|vyvoz)"
_STARY_RE = re.compile(rf"^{_KIND}_(\d{{8}})_(\d{{6}})\.pdf$", re.I)
# Prostřední část (jméno + vozidlo) je volitelná: u žádosti bez vyplněného
# jména i SPZ vznikne jen "zmena_20260808.pdf" a i tu je potřeba přečíst.
_NOVY_RE = re.compile(rf"^{_KIND}(?:_(.*?))?_(\d{{8}})(?:_(\d{{6}}))?\.pdf$", re.I)


def rozbor_nazvu(name: str) -> tuple[str, str, str] | None:
    """``název souboru -> (typ, datum ISO, čas HH:MM)`` nebo None.

    Jediné místo, které rozumí oběma tvarům — používá to výpis výstupů
    i předvyplnění, ať se nerozejdou.
    """
    base = os.path.basename(name or "")
    m = _STARY_RE.match(base)
    if m:
        kind, ymd, hms = m.group(1), m.group(2), m.group(3)
    else:
        m = _NOVY_RE.match(base)
        if not m:
            return None
        kind, ymd, hms = m.group(1), m.group(3), m.group(4) or ""
    return (kind.lower(),
            f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
            f"{hms[:2]}:{hms[2:4]}" if hms else "")


def _slug(text: str, maxlen: int = 28) -> str:
    """'AUTO CARDION s. r. o.' -> 'AUTO-CARDION-S-R-O'. Bez diakritiky a bez
    znaků, které by v názvu souboru nebo v URL dělaly potíže."""
    t = "".join(
        ch for ch in unicodedata.normalize("NFD", (text or "").upper())
        if not unicodedata.combining(ch)
    )
    t = re.sub(r"[^A-Z0-9]+", "-", t).strip("-")
    return t[:maxlen].strip("-")


def nazev_vystupu(kind: str, data: dict, ts: str, out_dir: str = "") -> str:
    """Sestaví název vygenerované žádosti: ``typ_JMENO_VOZIDLO_datum.pdf``.

    ``ts`` je ``%Y%m%d_%H%M%S``. Čas se do názvu dostane jen když by soubor
    jinak přepsal existující (tentýž člověk, totéž auto, tentýž den) — jinak
    by v názvu jen zabíral místo.
    """
    ymd, _, hms = ts.partition("_")
    jmeno = _slug(data.get("novy_jmeno") or data.get("puvodni_jmeno") or "")
    vozidlo = _slug(data.get("registracni_znacka") or data.get("vin") or "", 20)
    casti = [kind] + [p for p in (jmeno, vozidlo) if p] + [ymd]
    name = "_".join(casti) + ".pdf"
    if out_dir and os.path.exists(os.path.join(out_dir, name)):
        name = "_".join(casti + [hms]) + ".pdf"
    return name

INDEX_NAME = "vystupy.jsonl"
LIMIT = 300  # strop výpisu, ať modal nezhloupne u dotazu „všechno"


def _index_path(data_dir: str) -> str:
    return os.path.join(data_dir, INDEX_NAME)


def zapis_vystup(data_dir: str, files: list[str], data: dict) -> None:
    """Append-only index of what each generated PDF contains.

    The filename carries only a timestamp, so without this a question like
    „kdy jsem tiskl 3BR4008" could never be answered without opening all ~800
    PDFs. Written on every successful generate; never raises into that flow.
    """
    try:
        rec = {
            "files": [os.path.basename(f) for f in files if f],
            "rz": (data.get("registracni_znacka") or "").strip().upper(),
            "vin": (data.get("vin") or "").strip().upper(),
            "znacka": (data.get("znacka") or "").strip(),
            "od": (data.get("puvodni_jmeno") or "").strip(),
            "na": (data.get("novy_jmeno") or "").strip(),
            # Kdo žádost vyplnil — aby šlo hledat „co dělal Roman dnes".
            "profil": (data.get("profil") or "").strip(),
        }
        if not rec["files"]:
            return
        with open(_index_path(data_dir), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # hledání je pohodlí, generování žádosti nikdy neshodí


def nacti_index(data_dir: str) -> dict:
    """filename -> {rz, vin, znacka, od, na}. Poslední zápis vyhrává."""
    out: dict[str, dict] = {}
    path = _index_path(data_dir)
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                meta = {k: rec.get(k, "") for k in
                        ("rz", "vin", "znacka", "od", "na", "profil")}
                for fname in rec.get("files") or []:
                    out[fname] = meta
    except OSError:
        pass
    return out


def nacti_vystupy(data_dir: str) -> list[dict]:
    """Vygenerované žádosti — datum čte z názvu souboru (ts = %Y%m%d_%H%M%S)."""
    out_dir = os.path.join(data_dir, "output")
    if not os.path.isdir(out_dir):
        return []
    index = nacti_index(data_dir)
    rows = []
    for name in os.listdir(out_dir):
        rozbor = rozbor_nazvu(name)
        if not rozbor:
            continue
        kind, datum, cas = rozbor
        try:
            size = os.path.getsize(os.path.join(out_dir, name))
        except OSError:
            size = 0
        try:
            mtime = os.path.getmtime(os.path.join(out_dir, name))
        except OSError:
            mtime = 0.0
        meta = index.get(name, {})
        rows.append({
            "mtime": mtime,
            "file": name,
            "typ": TYPY.get(kind, kind),
            "kind": kind,
            "datum": datum,
            "cas": cas,
            "velikost": size,
            "url": f"/download/{name}",
            "rz": meta.get("rz", ""),
            "vin": meta.get("vin", ""),
            "znacka": meta.get("znacka", ""),
            "od": meta.get("od", ""),
            "na": meta.get("na", ""),
            "profil": meta.get("profil", ""),
        })
    # Řadí se podle skutečného času vzniku souboru, ne podle názvu: nový tvar
    # názvu čas nenese (přidává se jen při kolizi), takže se všechny žádosti
    # z jednoho dne dřív řadily v pořadí, v jakém je vrátila složka — a poslední
    # vyplněná žádost tak nebyla nahoře.
    rows.sort(key=lambda r: (r["datum"], r["mtime"]), reverse=True)
    return rows


# ── filtry ────────────────────────────────────────────────────────────────────

# Slova, která nikdy nesmí projít jako hledané jméno.
_STOP = {
    "kdy", "kde", "co", "jak", "kolik", "ktery", "ktere", "ktera", "kdo",
    "jsem", "jsi", "jsme", "byl", "bylo", "byly", "mam", "mame", "delal",
    "delali", "udelal", "udelali", "generoval", "vygeneroval", "tiskl",
    "tisknul", "vytiskl", "za", "na", "od", "do", "pro", "ve", "se", "po",
    "pri", "nebo", "the", "and", "vsechny", "vsech", "posledni", "poslednich",
    "den", "dne", "dni", "dnu", "mesic", "mesici", "mesicu", "tyden", "tydnu",
    "rok", "roce", "roku", "dnes", "vcera", "tento", "tenhle", "minuly",
    "letos", "loni", "zadost", "zadosti", "pdf", "vystup", "vystupy",
    "doklad", "doklady", "dokladu", "ppd", "firma", "firmy", "firmu", "firem",
    "ico", "auto", "auta", "vozidlo", "vozidla", "cislo", "castka", "castku",
    "jmeno", "hledej", "najdi", "ukaz", "chci", "videt", "seznam",
}
_STOP |= {stem for stem, _ in _MONTH_STEMS}

_RZ_RE = re.compile(r"^(?=.*\d)(?=.*[a-z])[a-z0-9]{5,8}$", re.I)
_VIN_RE = re.compile(r"^[a-z0-9]{17}$", re.I)


def _vehicle_terms(q: str) -> list[str]:
    """Tokeny, které vypadají jako RZ nebo VIN ('3BR4008', 'TMB…')."""
    out = []
    for w in re.findall(r"[A-Za-z0-9]{5,20}", q or ""):
        if _VIN_RE.match(w) or _RZ_RE.match(w):
            out.append(w.upper())
    return out


def _text_terms(f: str) -> list[str]:
    """Jména, která parser nespotřeboval — volný text pro plátce / firmy."""
    return [w for w in re.findall(r"[a-z0-9]{3,}", f) if w not in _STOP][:3]


def _in_period(datum: str, od: str | None, do: str | None) -> bool:
    if od and (datum or "") < od:
        return False
    if do and (datum or "") > do:
        return False
    return True


def _norm_datum(v) -> str:
    """Datum z xlsx může přijít jako datetime, date i text 'DD.MM.YYYY'."""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    m = re.match(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s[:10]


def _castka(v) -> float:
    try:
        return float(str(v).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


# ── hlavní vstup ──────────────────────────────────────────────────────────────

NAPOVEDA = ("Umím hledat vygenerované žádosti podle data nebo typu, doklady "
            "podle čísla, jména plátce nebo částky, vozidlo podle SPZ/VIN "
            "a firmy podle názvu nebo IČO. Zkus některý z příkladů.")

PRIKLADY = [
    "co jsem dělal 15.7.",
    "poslední zápisy",
    "kdy jsem tiskl 3BR4008",
    "převody tento měsíc",
    "doklad 152",
    "doklady za červenec",
    "kdo platil 1300",
    "firma Cardion",
    "IČO 04156854",
]


def hledej(q: str, vystupy: list[dict], doklady: list[dict], firmy: list[dict],
           today: date | None = None) -> dict:
    """Answer a Czech question over zadosti's own history.

    Returns ``{"understood", "headline", "detail", "period", "filters",
    "vystupy", "doklady", "firmy", "priklady"}``. Never guesses: an
    unparseable question comes back with ``understood=False``.
    """
    q = (q or "").strip()
    if not q:
        return _nic("", "Napiš, co hledáš.", None)

    f = fold(q)
    od, do, period = parse_period(q, today)
    obdobi = "" if period == "celkem" else f" ({period})"

    chce_doklady = any(w in f for w in ("doklad", "ppd", "paragon", "platil",
                                        "zaplatil", "castk", "prijmov"))
    chce_firmy = any(w in f for w in ("firma", "firmy", "firmu", "firem", "ico"))
    vozidla = _vehicle_terms(q)

    # 1) Konkrétní vozidlo (RZ / VIN) — nejsilnější signál, hledá napříč vším.
    if vozidla:
        return _podle_vozidla(vozidla, vystupy, doklady, obdobi, period)

    # 2) Doklad podle čísla — "doklad 152".
    if chce_doklady:
        m = re.search(r"\b(\d{1,6})\b", f)
        cislo = int(m.group(1)) if m else None
        # Rok ani částka nejsou číslo dokladu.
        if cislo is not None and (m.group(1).startswith("20") and len(m.group(1)) == 4):
            cislo = None
        if cislo is not None and any(str(d.get("cislo")) == str(cislo) for d in doklady):
            hits = [d for d in doklady if str(d.get("cislo")) == str(cislo)]
            return _ok(f"Doklad č. {cislo}", None, period, [], [],
                       _dok_out(hits), [])
        return _doklady_vypis(f, doklady, od, do, period, obdobi)

    # 3) Firmy — "firma Cardion", "IČO 04156854".
    if chce_firmy:
        return _firmy_vypis(f, q, firmy, period)

    # 4) Výstupy podle období / typu — hlavní případ ("co jsem dělal 15.7.").
    kind = None
    if "prevod" in f or "prepis" in f:
        kind = "zmeny"
    elif "zapis" in f or "nove vozidlo" in f or "nova vozidla" in f:
        kind = "zapis"
    elif "zmena udaj" in f or "zmeny udaj" in f or "technick" in f:
        kind = "zmena"

    hits = [v for v in vystupy if _in_period(v["datum"], od, do)]
    if kind:
        hits = [v for v in hits if v["kind"] == kind]

    if hits and (kind or period != "celkem" or "posledni" in f or "vsech" in f):
        # Jméno v dotazu se musí uplatnit I když je zadané období — „co dělal
        # Roman dnes" jinak vrátilo prostě všechno dnešní a jméno se zahodilo.
        popisky = [TYPY[kind]] if kind else []
        nalezene = None
        for term in _text_terms(f):
            zuzeno = [v for v in hits if sedi_vystup(v, term)]
            if zuzeno:
                hits = zuzeno
                nalezene = term
                popisky.append(term)
                break
        headline = f"{_zadosti(len(hits))}{obdobi}"
        if kind:
            headline += f" — {TYPY[kind]}"
        if nalezene:
            headline += f" — {nalezene}"
        return _ok(headline, _rozpad(hits) if not kind else None,
                   period, popisky, hits[:LIMIT], [], [])

    # 5) Volný text — jméno plátce v dokladech nebo název firmy.
    terms = _text_terms(f)
    if terms:
        alt = _volny_text(terms, vystupy, doklady, firmy, od, do, period, obdobi)
        if alt["understood"]:
            return alt
        # Dotaz nesl jméno, které nikde není. Vysypat místo toho celou historii
        # by vypadalo jako odpověď — a to je přesně to hádání, které nechceme.
        if not kind:
            return _nic(period, f"Na „{terms[0]}“ nic nemám.", NAPOVEDA)

    if hits:
        return _ok(f"{_zadosti(len(hits))}{obdobi}", _rozpad(hits), period, [],
                   hits[:LIMIT], [], [])

    # Typu i období jsme rozuměli, jen v nich nic není — to NENÍ „nerozumím".
    # Tvrdit opak by uživatele poslalo hledat chybu v dotazu místo v datech.
    if kind or period != "celkem":
        return _ok(f"Žádné žádosti{obdobi}" + (f" — {TYPY[kind]}" if kind else ""),
                   "Za tohle období tu nic není.", period,
                   [TYPY[kind]] if kind else [], [], [], [])

    return _nic(period, "Tomu nerozumím.", NAPOVEDA)


def _rozpad(hits: list[dict]) -> str | None:
    """'3× Převod, 1× Nové vozidlo' — ať je vidět skladba bez rolování."""
    counts: dict[str, int] = {}
    for v in hits:
        counts[v["typ"]] = counts.get(v["typ"], 0) + 1
    if len(counts) <= 1:
        return None
    return ", ".join(f"{n}× {t}" for t, n in
                     sorted(counts.items(), key=lambda kv: -kv[1]))


def _rzkey(s: str | None) -> str:
    """SPZ/VIN bez diakritiky, mezer a pomlček. Doklady mají v evidenci
    „1AB 2345", žádost ukládá „1AB2345" — bez tohohle by si vozidlo nenašlo
    vlastní doklad."""
    return re.sub(r"[^a-z0-9]", "", fold(s))


def sedi_vystup(v: dict, term: str) -> bool:
    """Odpovídá žádost hledanému výrazu?

    Hledá se PODŘETĚZCEM, ne na přesnou shodu — VIN má 17 znaků a nikdo ho
    nebude opisovat celý, aby našel jedno auto. Prochází SPZ, VIN, obě strany,
    značku vozidla i to, kdo žádost vyplnil (aby šlo „co dělal Roman dnes").
    """
    t = _rzkey(term)
    ft = fold(term)
    if t and (t in _rzkey(v.get("rz")) or t in _rzkey(v.get("vin"))):
        return True
    return bool(ft) and any(ft in fold(v.get(k)) for k in ("od", "na", "znacka", "profil"))


def _podle_vozidla(terms, vystupy, doklady, obdobi, period) -> dict:
    vys, dok = [], []
    for t in terms:
        ft = _rzkey(t)
        vys += [v for v in vystupy if ft and
                (ft in _rzkey(v.get("rz")) or ft in _rzkey(v.get("vin")))]
        dok += [d for d in doklady if ft and ft in _rzkey(d.get("vozidlo"))]
    # zachovat pořadí, zahodit duplicity
    vys = list({v["file"]: v for v in vys}.values())
    dok = list({str(d.get("cislo")): d for d in dok}.values())
    nazev = ", ".join(terms)
    if not vys and not dok:
        return _nic(period, f"Na „{nazev}“ nic nemám.",
                    "Vozidlo hledám v SPZ/VIN vygenerovaných žádostí a v dokladech. "
                    "Starší žádosti nemusí být v indexu.")
    casti = []
    if vys:
        casti.append(_zadosti(len(vys)))
    if dok:
        casti.append(_doklady(len(dok)))
    prvni = min((v["datum"] for v in vys), default=None)
    posledni = max((v["datum"] for v in vys), default=None)
    detail = None
    if prvni and posledni:
        detail = (f"Naposledy {_cz_date(posledni)}." if prvni == posledni
                  else f"Od {_cz_date(prvni)} do {_cz_date(posledni)}.")
    return _ok(f"{nazev} — {' a '.join(casti)}", detail, period, [nazev],
               vys[:LIMIT], _dok_out(dok), [])


def _dok_out(rows: list[dict]) -> list[dict]:
    out = []
    for d in rows[:LIMIT]:
        cislo = d.get("cislo")
        out.append({
            "cislo": cislo,
            "datum": _norm_datum(d.get("datum")),
            "prijato_od": d.get("prijato_od") or "",
            "castka": d.get("castka") or "",
            "ucel": d.get("ucel") or "",
            "vozidlo": d.get("vozidlo") or "",
            "url": f"/download/ppd_{cislo}.pdf" if cislo not in (None, "") else "",
        })
    return out


def _doklady_vypis(f, doklady, od, do, period, obdobi) -> dict:
    hits = [d for d in doklady if _in_period(_norm_datum(d.get("datum")), od, do)]
    # částka — "kdo platil 1300"
    m = re.search(r"\b(\d{3,7})\b", f)
    if m and not (m.group(1).startswith("20") and len(m.group(1)) == 4):
        castka = float(m.group(1))
        podle_castky = [d for d in hits if _castka(d.get("castka")) == castka]
        if podle_castky:
            total = sum(_castka(d.get("castka")) for d in podle_castky)
            return _ok(f"{_doklady(len(podle_castky))} po {kc(castka)}{obdobi} "
                       f"— celkem {kc(total)}",
                       None, period, [kc(castka)], [], _dok_out(podle_castky), [])
    # jméno plátce
    for term in _text_terms(f):
        podle_jmena = [d for d in hits if term in fold(d.get("prijato_od"))]
        if podle_jmena:
            total = sum(_castka(d.get("castka")) for d in podle_jmena)
            return _ok(f"„{term}“ — {_doklady(len(podle_jmena))} za {kc(total)}{obdobi}",
                       None, period, [term], [], _dok_out(podle_jmena), [])
    if hits:
        total = sum(_castka(d.get("castka")) for d in hits)
        return _ok(f"{_doklady(len(hits))} za {kc(total)}{obdobi}", None, period,
                   [], [], _dok_out(hits), [])
    return _nic(period, f"Žádné doklady{obdobi}.", None)


def _firmy_vypis(f, q, firmy, period) -> dict:
    ico = re.search(r"\b(\d{8})\b", q or "")
    if ico:
        hits = [x for x in firmy if str(x.get("ico") or "").strip() == ico.group(1)]
        if hits:
            return _ok(f"IČO {ico.group(1)}", None, period, [], [], [], hits)
        return _nic(period, f"Firmu s IČO {ico.group(1)} nemám.", None)
    for term in _text_terms(f):
        hits = [x for x in firmy if term in fold(x.get("nazev"))]
        if hits:
            return _ok(f"„{term}“ — {len(hits)} "
                       f"{_pl(len(hits), 'firma', 'firmy', 'firem')}",
                       None, period, [term], [], [], hits)
    if firmy:
        return _ok(f"{len(firmy)} {_pl(len(firmy), 'firma', 'firmy', 'firem')}",
                   "Uložené firmy:", period, [], [], [], firmy)
    return _nic(period, "Žádné uložené firmy.", None)


def _volny_text(terms, vystupy, doklady, firmy, od, do, period, obdobi) -> dict:
    for term in terms:
        dok = [d for d in doklady
               if term in fold(d.get("prijato_od"))
               and _in_period(_norm_datum(d.get("datum")), od, do)]
        vys = [v for v in vystupy
               if sedi_vystup(v, term) and _in_period(v["datum"], od, do)]
        fir = [x for x in firmy if term in fold(x.get("nazev"))]
        if dok or vys or fir:
            casti = []
            if vys:
                casti.append(_zadosti(len(vys)))
            if dok:
                casti.append(_doklady(len(dok)))
            if fir:
                casti.append(f"{len(fir)} {_pl(len(fir), 'firma', 'firmy', 'firem')}")
            return _ok(f"„{term}“{obdobi} — {', '.join(casti)}", None, period,
                       [term], vys[:LIMIT], _dok_out(dok), fir)
    return _nic(period, "", None)


def _ok(headline, detail, period, filters, vystupy, doklady, firmy) -> dict:
    # `limit` jde ven, aby UI mohlo přiznat oříznutý výpis. Headline říká
    # „462 žádostí", ale vypsat jich jde 300 — mlčet o tom by byla přesně ta
    # tichá nepřesnost, kterou tahle appka nesmí dělat.
    return {"understood": True, "headline": headline, "detail": detail,
            "period": period, "filters": filters, "vystupy": vystupy,
            "doklady": doklady, "firmy": firmy, "priklady": PRIKLADY,
            "limit": LIMIT}


def _nic(period, headline, detail) -> dict:
    return {"understood": False, "headline": headline, "detail": detail,
            "period": period, "filters": [], "vystupy": [], "doklady": [],
            "firmy": [], "priklady": PRIKLADY, "limit": LIMIT}
