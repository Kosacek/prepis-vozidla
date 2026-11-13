"""Version history of Evidence úkonů, newest first.

Feeds "Co umí Evidence" (templates/_novinky.html, data in novinky.py): the
newest release pops up as a card once per device after an update, then slides
away to reveal a sheet with only what the app can do NOW. The "v2.x ⓘ" button
next to "Odhlásit" opens the sheet directly.

Adding a release (every user-visible update — see ../AGENTS.md): put a new
Release at the TOP. Title is one short sentence in user terms, at most two
short points, Czech, informal "ty". `demo` names a partial in
templates/demos/ that shows the change in motion; older entries
reconstructed from git history have none.

Sheet fields: `oblast` (section key from novinky.SEKCE; None = not on the
sheet), `nahrazuje` (older versions this one makes obsolete), `zastarale`
(no longer true / nothing to show), `nazev` (card title, default `title`),
`radek` (one-line card text, default first point). Newest wording wins; give
every new release an `oblast` and say what it replaces.
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
    oblast: str | None = None
    nahrazuje: tuple[str, ...] = ()
    zastarale: bool = False
    nazev: str | None = None
    radek: str | None = None


RELEASES: tuple[Release, ...] = (
    Release(
        "2.9.3", date(2026, 11, 13),
        "Novinky na jedné stránce",
        ("Nejnovější změna vyskočí jako dřív a pod ní uvidíš všechno, co Evidence umí – bez starých verzí.",
         "U zaplacené faktury ikona banky říká, že platba dorazila sama."),
        oblast="prehled", nazev="Všechno na jedné stránce",
        radek="Klepnutím na verzi nahoře uvidíš, co Evidence umí.",
    ),
    Release(
        "2.9.2", date(2026, 11, 13),
        "Jeden kód na všechno",
        ("Číslo faktury je zároveň kód: na zadosti.spznaklic.cz/5732 vytiskneš "
         "fakturu i všechny žádosti k ní.",
         "„Sdílet kódem“ kód obnoví na dalších 30 dní, pořád stejný."),
        demo="v2_9_2",
        oblast="doklady", nazev="Jeden kód na faktury", radek="Číslo faktury je i kód: vytiskneš fakturu i všechny její žádosti.",
    ),
    Release(
        "2.9.1", date(2026, 11, 13),
        "Každý doklad je teď faktura s QR kódem",
        ("Zákazník zaplatí převodem a úkon se ti sám označí jako zaplacený.",),
        demo="v2_9_1",
        oblast="doklady", nahrazuje=("2.9",), nazev="Faktura s QR kódem", radek="Zákazník zaplatí převodem a úkon se sám označí jako zaplacený.",
    ),
    Release(
        "2.9", date(2026, 11, 12),
        "Doklad převodem s QR kódem",
        ("V Novém dokladu zvolíš Hotově, nebo Převodem – převodem vyjde faktura s QR Platbou.",
         "Jakmile platba dorazí na účet, úkony se samy označí jako zaplacené."),
        demo="v2_9",
        zastarale=True,
    ),
    Release(
        "2.8", date(2026, 11, 12),
        "Doklad vytiskneš nebo pošleš kódem",
        ("Ikonou sdílení u dokladu zvolíš Tisk nebo Sdílet kódem — bez odbočky do žádostí.",
         "Řádek ukáže firmu, SPZ i VIN a zezelená, když jsou úkony zaplacené."),
        demo="v2_8",
        oblast="doklady", nazev="Tisk nebo sdílení dokladu", radek="Ikonou sdílení zvolíš Tisk nebo Sdílet kódem; zaplacený řádek zezelená.",
    ),
    Release(
        "2.7.3", date(2026, 11, 11),
        "Nový majitel na techničáku = nový úkon",
        ("Nový majitel se k úkonu zapíše a jiná SPZ než v evidenci čeká ve Zkontroluj.",
         "Cenu nového auta přepíšeš klepnutím — třeba elektrika bez poplatku."),
        oblast="technicak", nazev="Nový majitel = nový úkon", radek="Nový majitel se zapíše; jiná SPZ než v evidenci počká ve Zkontroluj.",
    ),
    Release(
        "2.7.2", date(2026, 11, 5),
        "Firmy barevně a úprava nad techničákem",
        ("Firmu vybereš s barevnou tečkou stejně jako v Úkonech — v Dokladech i ve skenu.",
         "Úprava úkonu se otevře nad techničákem; karta má fotku vpravo a cenu u poznámky."),
        demo="v2_7_2",
        oblast="firmy", nazev="Firmy s barevnou tečkou", radek="Firmu vybereš s barvou stejně jako v Úkonech – v Dokladech i ve skenu.",
    ),
    Release(
        "2.7.1", date(2026, 11, 5),
        "Sken techničáku je přehlednější",
        ("Každé auto má vlastní firmu, typ i poznámku — žádná společná lišta.",
         "V kartách je hned vidět SPZ, ORV a firma; v souhrnu vidíš jen to, co se opravdu stalo."),
        demo="v2_7_1",
        oblast="technicak", nahrazuje=("2.7",), nazev="Karta auta ze skenu", radek="Každé auto má vlastní firmu, typ a poznámku; nečitelnou fotku vyfotíš znovu.",
    ),
    Release(
        "2.7", date(2026, 11, 5),
        "Techničák víc pod kontrolou",
        ("Firmu a typ vybereš u auta — a konečně můžeš napsat poznámku.",
         "Nečitelnou fotku vyfotíš znovu; když už auto v evidenci je, sken se zeptá, než založí druhý úkon."),
        demo="v2_7",
        zastarale=True,
    ),
    Release(
        "2.6", date(2026, 11, 5),
        "Doklad vyplníš z IČO",
        ("Napiš IČO a jméno i adresa se doplní z ARES.",
         "Úkony firmy si sbalíš, VIN nebo RZ můžeš napsat i ručně."),
        demo="v2_6",
        oblast="doklady", nazev="Doklad z IČO", radek="Napiš IČO a jméno i adresa se doplní z ARES.",
    ),
    Release(
        "2.5.1", date(2026, 11, 2),
        "Koš v Dokladech maže doklad, ne úkon",
        ("Úkony v dokladu zůstanou, jak jsou.",),
        zastarale=True,
    ),
    Release(
        "2.5", date(2026, 10, 26),
        "Doklady ukážou, co platí",
        ("Klepni na doklad a vyjedou jeho úkony. Nezaplacený má oranžové Zaplatit, jen potvrdíš.",
         "Doklady najdeš i podle firmy a výběr měsíce už funguje i na iPhonu."),
        demo="v2_5",
        oblast="doklady", nahrazuje=("1.8", "2.5.1"), nazev="Doklady ukážou, co platí", radek="Klepni na doklad a vyjedou jeho úkony; nezaplacený má oranžové Zaplatit.",
    ),
    Release(
        "2.4", date(2026, 10, 19),
        "Přehlednější úkony na mobilu",
        ("Značka a cena nahoře, platba je jedno tlačítko: Zaplatit ↔ ✓ Zaplaceno.",
         "Kdo úkon přidal ukazuje iniciála, smazat je pod košem vpravo."),
        demo="v2_4",
        oblast="ukony", nazev="Úkon na mobilu", radek="Značka a cena nahoře, platba je jedno tlačítko: Zaplatit ↔ ✓ Zaplaceno.",
    ),
    Release(
        "2.3", date(2026, 10, 19),
        "Techničák ti nezmizí pod rukama",
        ("Nový techničák rovnou přepíše staré ORV i značku, nic nepotvrzuješ.",
         "Po úpravě auta se vrátíš do přehledu skenu. Poslední sken otevřeš i později přes ⟲."),
        demo="v2_3",
        oblast="technicak", nazev="Poslední sken po ruce", radek="Po úpravě auta se vrátíš do přehledu skenu; poslední sken otevřeš přes ⟲.",
    ),
    Release(
        "2.2", date(2026, 10, 13),
        "Zeptej se navazuje na předchozí otázku",
        ("Ptej se dál – třeba „a v září?“ nebo „a pro Albion?“ – a ví, o čem je řeč.",
         "Předchozí otázky a odpovědi zůstávají vidět nad sebou."),
        demo="v2_2",
        oblast="prehled", nahrazuje=("1.5",), nazev="Zeptej se", radek="Ptej se normální větou a doptávej se dál – ví, o čem je řeč.",
    ),
    Release(
        "2.1", date(2026, 10, 12),
        "V Příchozích vidíš, co je duplikát",
        ("U možného duplikátu uvidíš stávající i příchozí úkon jako běžné řádky "
         "a hned poznáš, co se liší.",
         "Klepnutím na stávající úkon ho otevřeš, aniž bys odešel z Příchozích."),
        demo="v2_1",
        oblast="firmy", nazev="Duplikáty v Příchozích", radek="U možného duplikátu uvidíš oba úkony vedle sebe a hned poznáš rozdíl.",
    ),
    Release(
        "2.0", date(2026, 10, 11),
        "Nově ti pomáhá AI",
        ("Zeptej se – napiš otázku vlastními slovy a AI ti ji najde v úkonech.",
         "Techničák v Úkonech – vyfoť techničáky a AI sama doplní značky a ORV."),
        demo="ai",
        zastarale=True,
    ),
    Release(
        "1.9", date(2026, 10, 11),
        "Přehled za měsíc i celý rok",
        ("V Přehledu si vybereš měsíc nebo celý rok a všechny grafy se přepnou.",
         "U firem a typů úkonů přepínáš mezi korunami a počtem."),
        demo="v1_9",
        oblast="prehled", nazev="Přehled za měsíc i rok", radek="Vybereš měsíc nebo celý rok a grafy se přepnou; koruny nebo počet.",
    ),
    Release(
        "1.8", date(2026, 10, 8),
        "Pokladní doklady a nový seznam úkonů",
        ("Pokladní doklady ze žádostí najdeš v záložce Doklady.",
         "Úkony se otevřou rovnou na celém seznamu, nový přidáš tlačítkem."),
        demo="v1_8",
        zastarale=True,
    ),
    Release(
        "1.7", date(2026, 9, 18),
        "Všechno bez čekání",
        ("Zaplacení, částečná platba, mazání i filtry fungují bez načítání "
         "stránky. Čísla v Přehledu jsou větší a naběhnou animací.",),
        demo="v1_7",
        oblast="ukony", nahrazuje=("1.6",), nazev="Všechno bez čekání", radek="Placení, mazání i filtry fungují bez načítání stránky.",
    ),
    Release(
        "1.6", date(2026, 8, 30),
        "Rychlejší zadávání",
        ("Úkon se uloží a firma přepne bez načítání stránky.",
         "Firmy vybíráš podle barevných teček přímo ve formuláři."),
        demo="v1_6",
        zastarale=True,
    ),
    Release(
        "1.5", date(2026, 8, 3),
        "Zeptej se",
        ("Napiš otázku a evidence ti spočítá odpověď – třeba kolik úkonů "
         "bylo ve středu – a vypíše i konkrétní úkony.",),
        demo="v1_5",
        zastarale=True,
    ),
    Release(
        "1.4", date(2026, 7, 16),
        "VIN se doplní sám",
        ("Po zadání ORV se VIN doplní automaticky.",
         "Úkony mají nový přehledný seznam s čitelnými poznámkami."),
        demo="v1_4",
        oblast="ukony", nazev="VIN se doplní sám", radek="Po zadání ORV se VIN doplní automaticky.",
    ),
    Release(
        "1.3", date(2026, 7, 1),
        "Kdo co vyřídil",
        ("U každého úkonu je vidět, kdo ho zpracoval. Úkon upravíš v okně "
         "přímo z Přehledu.",),
        demo="v1_3",
        oblast="ukony", nazev="Kdo co vyřídil", radek="U každého úkonu je vidět, kdo ho zpracoval.",
    ),
    Release(
        "1.2", date(2026, 6, 28),
        "Hledání a barvy firem",
        ("V úkonech hledáš živě při psaní a každá firma má svou barvu.",),
        demo="v1_2",
        oblast="ukony", nazev="Hledání a barvy firem", radek="V úkonech hledáš živě při psaní a každá firma má svou barvu.",
    ),
    Release(
        "1.1", date(2026, 6, 14),
        "Propojení se žádostmi",
        ("Hotové žádosti se samy objeví v Příchozích.",
         "Každá firma může mít vlastní ceny."),
        demo="v1_1",
        oblast="firmy", nazev="Propojení se žádostmi", radek="Hotové žádosti se samy objeví v Příchozích; firma může mít vlastní ceny.",
    ),
    Release(
        "1.0", date(2026, 6, 9),
        "Evidence je tady",
        ("Úkony pro všechny firmy na jednom místě – přehled, placení "
         "a export do Excelu.",),
        demo="v1_0",
        oblast="prehled", nazev="Přehled a export", radek="Úkony všech firem na jednom místě – přehled, placení, export do Excelu.",
    ),
)

CURRENT_VERSION = RELEASES[0].version
