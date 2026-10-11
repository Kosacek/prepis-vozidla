"""Version history of Evidence úkonů, newest first.

Shown by the "v2.0 ⓘ" button next to "Odhlásit" (a browsable "what's new",
templates/_whats_new.html); the newest entry also opens by itself once per
device after an update.

Adding a release (every user-visible update — see ../AGENTS.md): put a new
Release at the TOP. Title is one short sentence in user terms, at most two
short points, Czech, informal "ty". `demo` names a partial in
templates/demos/ that shows the change in motion; older entries
reconstructed from git history have none.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Release:
    version: str
    date: date
    title: str
    points: tuple[str, ...] = field(default_factory=tuple)
    demo: str | None = None


RELEASES: tuple[Release, ...] = (
    Release(
        "2.0", date(2026, 10, 11),
        "Nově ti pomáhá AI",
        ("Zeptej se – napiš otázku vlastními slovy a AI ti ji najde v úkonech.",
         "Techničák v Úkonech – vyfoť techničáky a AI sama doplní značky a ORV."),
        demo="ai",
    ),
    Release(
        "1.9", date(2026, 10, 11),
        "Přehled za měsíc i celý rok",
        ("V Přehledu si vybereš měsíc nebo celý rok a všechny grafy se přepnou.",
         "U firem a typů úkonů přepínáš mezi korunami a počtem."),
    ),
    Release(
        "1.8", date(2026, 10, 8),
        "Pokladní doklady a nový seznam úkonů",
        ("Pokladní doklady ze žádostí najdeš v záložce Doklady.",
         "Úkony se otevřou rovnou na celém seznamu, nový přidáš tlačítkem."),
    ),
    Release(
        "1.7", date(2026, 9, 18),
        "Všechno bez čekání",
        ("Zaplacení, částečná platba, mazání i filtry fungují bez načítání "
         "stránky. Čísla v Přehledu jsou větší a naběhnou animací.",),
    ),
    Release(
        "1.6", date(2026, 8, 30),
        "Rychlejší zadávání",
        ("Úkon se uloží a firma přepne bez načítání stránky.",
         "Firmy vybíráš podle barevných teček přímo ve formuláři."),
    ),
    Release(
        "1.5", date(2026, 8, 3),
        "Zeptej se",
        ("Napiš otázku a evidence ti spočítá odpověď – třeba kolik úkonů "
         "bylo ve středu – a vypíše i konkrétní úkony.",),
    ),
    Release(
        "1.4", date(2026, 7, 16),
        "VIN se doplní sám",
        ("Po zadání ORV se VIN doplní automaticky.",
         "Úkony mají nový přehledný seznam s čitelnými poznámkami."),
    ),
    Release(
        "1.3", date(2026, 7, 1),
        "Kdo co vyřídil",
        ("U každého úkonu je vidět, kdo ho zpracoval. Úkon upravíš v okně "
         "přímo z Přehledu.",),
    ),
    Release(
        "1.2", date(2026, 6, 28),
        "Hledání a barvy firem",
        ("V úkonech hledáš živě při psaní a každá firma má svou barvu.",),
    ),
    Release(
        "1.1", date(2026, 6, 14),
        "Propojení se žádostmi",
        ("Hotové žádosti se samy objeví v Příchozích.",
         "Každá firma může mít vlastní ceny."),
    ),
    Release(
        "1.0", date(2026, 6, 9),
        "Evidence je tady",
        ("Úkony pro všechny firmy na jednom místě – přehled, placení "
         "a export do Excelu.",),
    ),
)

CURRENT_VERSION = RELEASES[0].version
