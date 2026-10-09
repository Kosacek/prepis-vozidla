"""Live tool-planning check. Run only with ANTHROPIC_API_KEY set."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.ai_assistant import ask  # noqa: E402


SPEC = [
    ("Ukaž mi na grafu průměr podle dne v týdnu a kdo dělá víc, jestli Roman nebo David", "agregace", {"skupiny": ["den_v_tydnu", "zpracoval"], "prumer_na": "den_v_tydnu", "filtry.zpracoval": ["Roman", "David"]}),
    ("kolik jsme vydělali tento měsíc", "agregace", {"metrika": "soucet_kc", "obdobi": "this"}),
    ("jak jsme na tom s penězi", "doptat_se", {}),
    ("co nám kdo dluží", "agregace", {"metrika": "nezaplaceno_kc", "skupiny": ["firma"]}),
    ("albion", "agregace", {"obdobi": "this", "filtry.firma_ids": "Albion"}),
    # den / týden / měsíc jsou všechny rozumné odpovědi → kontroluje se jen metrika
    ("kdy bylo nejvíc práce", "agregace", {"metrika": "pocet"}),
    ("kolik převodů v září", "agregace", {"metrika": "pocet", "obdobi": "september", "filtry.typy": ["PŘEVOD"]}),
    ("srovnej červenec a srpen", "agregace", {"skupiny": ["mesic"], "obdobi": "july_august"}),
    ("kdo dělá nejvíc", "agregace", {"metrika": "pocet", "skupiny": ["zpracoval"]}),
    ("jaká je průměrná cena úkonu u cardionu", "agregace", {"metrika": "prumer_kc", "filtry.firma_ids": "Cardion"}),
    ("kolik bylo elektrických značek", "agregace", {"metrika": "pocet", "filtry.poznamka_obsahuje": "EL"}),
    ("ukaž úkony bez spz", "seznam_ukonu", {"filtry.bez_rz": True}),
    ("kolik toho průměrně uděláme v pondělí", "agregace", {"metrika": "pocet", "prumer_na": "den_v_tydnu", "filtry.dny_v_tydnu": [1]}),
    ("vývoj po týdnech od července", "agregace", {"skupiny": ["tyden"], "obdobi": "since_july"}),
    ("které firmy dluží víc než 5000", "agregace", {"metrika": "nezaplaceno_kc", "skupiny": ["firma"], "jen_kde_vic_nez": 5000}),
    ("poslední úkony od Romana", "seznam_ukonu", {"filtry.zpracoval": ["Roman"]}),
    ("kolik úkonů nemá vyplněno, kdo je dělal", "agregace", {"metrika": "pocet", "skupiny": ["zpracoval"]}),
    ("nejlepší firma podle peněz", "agregace", {"metrika": "soucet_kc", "skupiny": ["firma"]}),
    ("kolik 3RZ za poslední 3 měsíce", "agregace", {"metrika": "pocet", "obdobi": "last_three", "filtry.typy": ["3RZ"]}),
    ("jaký byl včerejšek", "agregace", {"obdobi": "yesterday"}),
]

VARIANTS = [
    ("kolik penez zari", "agregace", {"metrika": "soucet_kc", "obdobi": "september"}),
    ("albion", "agregace", {"obdobi": "this", "filtry.firma_ids": "Albion"}),
    ("kdo vic roman nebo david", "agregace", {"skupiny": ["zpracoval"], "filtry.zpracoval": ["Roman", "David"]}),
    ("dluhy", "agregace", {"metrika": "nezaplaceno_kc"}),
    ("ppd zari", "doklady_ppd", {"obdobi": "september"}),
    ("kolik ukonu vcera", "agregace", {"metrika": "pocet", "obdobi": "yesterday"}),
    ("preovdy zari", "agregace", {"metrika": "pocet", "obdobi": "september"}),
    ("penize jak to jde", "doptat_se", {}),
]


def _period(label: str, today: date) -> dict:
    if label == "this":
        return {"od": today.replace(day=1).isoformat(), "do": today.isoformat()}
    if label == "yesterday":
        day = (today - timedelta(days=1)).isoformat()
        return {"od": day, "do": day}
    if label == "last_three":
        month = today.month - 2
        start = date(today.year - 1, month + 12, 1) if month < 1 else date(today.year, month, 1)
        return {"od": start.isoformat(), "do": today.isoformat()}
    year = today.year
    ranges = {"september": (f"{year}-09-01", f"{year}-09-30"),
              "july_august": (f"{year}-07-01", f"{year}-08-31"),
              "since_july": (f"{year}-07-01", today.isoformat())}
    od, do = ranges[label]
    return {"od": od, "do": do}


def _matches(call: dict, expected: dict, today: date, company_ids: dict) -> bool:
    params = call.get("input") or {}
    for key, wanted in expected.items():
        if key == "obdobi":
            actual = params.get("obdobi") or {}
            target = _period(wanted, today)
            if actual.get("od") != target["od"] or actual.get("do") not in (target["do"], _month_end_equivalent(target["do"], today)):
                return False
            continue
        actual = params
        for part in key.split("."):
            actual = actual.get(part) if isinstance(actual, dict) else None
        if key == "filtry.firma_ids":
            wanted = [company_ids.get(wanted.lower())]
        if isinstance(wanted, list):
            if not isinstance(actual, list) or (key in {"skupiny", "filtry.zpracoval"} and set(actual) != set(wanted)) or (key not in {"skupiny", "filtry.zpracoval"} and actual != wanted):
                return False
        elif actual != wanted:
            return False
    return True


def _month_end_equivalent(end: str, today: date) -> str:
    if end == today.isoformat():
        next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        return (next_month - timedelta(days=1)).isoformat()
    return end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--db", default="data/tracker.db")
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 10, 8))
    parser.add_argument("--verbose", action="store_true", help="u chyb vypiš větu a volání")
    parser.add_argument("--only", type=lambda s: {int(x) for x in s.split(",")},
                        help="spusť jen tato čísla otázek, např. 6,8,12")
    args = parser.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Přeskakuji live eval: chybí ANTHROPIC_API_KEY.")
        return 0
    if not Path(args.db).is_file():
        parser.error(f"Databáze neexistuje: {args.db}")
    os.environ["ZEPTEJ_EFFORT"] = args.effort
    with sqlite3.connect(args.db) as conn:
        company_ids = {name.lower(): fid for fid, name in conn.execute("SELECT id, zkratka FROM firmy")}
    score = 0
    variant_score = 0
    print(f"{'#':>2}  {'Výsledek':8} {'Nástroj':15} Otázka")
    for index, (question, name, expected) in enumerate([*SPEC, *VARIANTS], 1):
        if args.only and index not in args.only:
            continue
        try:
            result = ask(question, db_path=args.db, today=args.today)
            if name == "doptat_se":
                good = result["typ"] == "doptat_se"
            else:
                good = result["veta_overena"] and any(
                    call["name"] == name and _matches(call, expected, args.today, company_ids)
                    for call in result["volani"])
            actual = result["typ"] if name == "doptat_se" else ",".join(c["name"] for c in result["volani"])
            if not good and args.verbose:
                print(f"    ↳ věta ({'ověřena' if result['veta_overena'] else 'NEOVĚŘENA'}): {result['veta']}")
                for call in result["volani"]:
                    print(f"    ↳ {call['name']} {json.dumps(call['input'], ensure_ascii=False)}")
                print(f"    ↳ čekáno: {name} {json.dumps(expected, ensure_ascii=False)}")
        except Exception as exc:
            good, actual = False, type(exc).__name__
            cause = exc.__cause__ or exc
            print(f"    ↳ {type(cause).__name__}: {str(cause)[:300]}")
        if good and index <= len(SPEC):
            score += 1
        elif good:
            variant_score += 1
        print(f"{index:>2}  {'OK' if good else 'CHYBA':8} {actual[:15]:15} {question}")
    print(f"Spec: {score}/{len(SPEC)} (minimum 18/20)")
    print(f"Varianty: {variant_score}/{len(VARIANTS)} · celkem {score + variant_score}/{len(SPEC) + len(VARIANTS)}")
    return 0 if score >= 18 else 1


if __name__ == "__main__":
    raise SystemExit(main())
