"""Version history of Žádosti (přepis vozidel), newest first.

Shown by the "v1.21.0 ⓘ" label in the bottom bar (a browsable "what's new",
templates/_whats_new.html); the newest entry also opens by itself once per
device after an update. Versions are the real app versions (VERSION);
patch releases are listed only when people would notice them.

Adding a release (every user-visible update — see ../AGENTS.md): put a new
Release at the TOP when you bump VERSION. Title is one short sentence in
user terms, at most two short points, Czech, informal "ty". `demo` names a
partial in templates/demos/ that shows the change in motion; entries
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
    Release("1.25.0", date(2026, 10, 14), "Náhled před tiskem",
            ("Kód teď vždycky ukáže obrázek každého dokumentu, ať hned vidíš, "
             "že tiskneš ten správný.",
             "Plná moc k žádosti se přidá pod stejný kód."),
            demo="v1_25_0"),
    Release("1.24.0", date(2026, 10, 13), "Zeptej se se doptá a navazuje",
            ("Napíšeš jméno firmy jen přibližně a nabídne ti tu správnou.",
             "Můžeš se ptát dál – třeba „a za říjen?“ – a ví, o čem je řeč."),
            demo="v1_24_0"),
    Release("1.23.0", date(2026, 10, 13), "Hledání rozumí normální větě",
            ("Zeptej se třeba „Kolik převodů udělal Roman tento měsíc?“ – "
             "odpověď spočítá z tvých žádostí a dokladů.",
             "Kroky se plynule přesouvají a Doklady mají nový vzhled."),
            demo="v1_23_0"),
    Release("1.22.0", date(2026, 10, 12), "Historie verzí",
            ("Klepni na číslo verze vlevo dole a uvidíš, co se kdy změnilo – "
             "listuješ šipkami nebo přejetím.",),
            demo="v1_22_0"),
    Release("1.21.0", date(2026, 10, 9), "Doklady se samy propíšou do evidence",
            ("Každý vystavený pokladní doklad se pošle do evidence – i když ho "
             "smažeš nebo obnovíš.",),
            demo="v1_21_0"),
    Release("1.20.0", date(2026, 10, 8), "Otočení kamery a nová Správa firem",
            ("Ikonou nebo klepnutím do náhledu otočíš obraz kamery o 180°.",
             "Správa firem má nový vzhled a uloženou firmu vybereš jen z klávesnice."),
            demo="v1_20_0"),
    Release("1.19.0", date(2026, 10, 8), "Plynulejší skenování",
            ("Sken techničáku už nepřeskakuje kroky a všechno vyplníš plynule "
             "z klávesnice.",),
            demo="v1_19_0"),
    Release("1.18.0", date(2026, 10, 8), "Sdílecí kód všude",
            ("Sdílecí kód funguje i pro plnou moc, historii a Doklady.",
             "Kroky mají všude stejnou velikost."),
            demo="v1_18_0"),
    Release("1.17.0", date(2026, 10, 8), "Rychlejší sken a rovnou do evidence",
            ("Sken používá novou, rychlejší AI.",
             "Hotovou žádost přidáš do evidence jedním tlačítkem."),
            demo="v1_17_0"),
    Release("1.16.0", date(2026, 9, 30), "Plná moc i pro Romana",
            ("Plnou moc teď vystaví i Roman a přihlášení snese mezeru navíc.",),
            demo="v1_16_0"),
    Release("1.15.0", date(2026, 9, 21), "Rychlejší žádosti",
            ("Žádost se sestaví výrazně rychleji, i po delší pauze.",),
            demo="v1_15_0"),
    Release("1.14.0", date(2026, 9, 18), "Krátký sdílecí odkaz",
            ("Žádost pošleš krátkým odkazem /1234 – otevře celý balík "
             "dokumentů přes celou obrazovku.",),
            demo="v1_14_0"),
    Release("1.11.0", date(2026, 9, 16), "Správné datum na tiskopisu",
            ("Datum se řídí úředními hodinami přepážky, ne automaticky zítřkem.",),
            demo="v1_11_0"),
    Release("1.10.0", date(2026, 9, 15), "Náhled dokladu a víc vozidel",
            ("Doklad si před vystavením prohlédneš a přidáš na něj víc vozidel.",),
            demo="v1_10_0"),
    Release("1.9.0", date(2026, 9, 2), "Chytřejší propojení s evidencí",
            ("Firma se páruje podle IČO, i z prodávajícího, a evidence zná "
             "elektrické značky.",),
            demo="v1_9_0"),
    Release("1.8.0", date(2026, 9, 1), "Filtry v hledání",
            ("Hledání má naklikávací filtry a měsíc zadáš číslem.",),
            demo="v1_8_0"),
    Release("1.7.0", date(2026, 8, 31), "Čistší plná moc",
            ("Nezaškrtnutá RZ nebo VIN se na papír vůbec nevytiskne.",),
            demo="v1_7_0"),
    Release("1.6.0", date(2026, 8, 11), "Žádost na vývoz",
            ("Nový typ žádosti: vývoz vozidla. První krok má volby vedle sebe.",),
            demo="v1_6_0"),
    Release("1.5.0", date(2026, 8, 9), "Plná moc",
            ("Vystavíš plnou moc k zastupování na registru vozidel.",),
            demo="v1_5_0"),
    Release("1.4.0", date(2026, 8, 8), "Tabulka s registrační značkou",
            ("V Ostatních úkonech je nová žádost o tabulku s RZ.",),
            demo="v1_4_0"),
    Release("1.3.32", date(2026, 8, 3), "Hledání",
            ("Najdeš žádosti, doklady i firmy na jednom místě – bez hrabání na NAS.",),
            demo="v1_3_32"),
    Release("1.3.22", date(2026, 7, 11), "Úkon do evidence rovnou ze žádosti",
            ("Na poslední stránce vybereš firmu, typ a cenu a úkon se zapíše "
             "do evidence.",),
            demo="v1_3_22"),
    Release("1.3.13", date(2026, 6, 15), "Tisk jedním klepnutím",
            ("Žádost se vytiskne jedním klepnutím, doklad rovnou na A5.",),
            demo="v1_3_13"),
    Release("1.3.0", date(2026, 6, 2), "Vystavené doklady",
            ("Seznam všech vystavených pokladních dokladů s hledáním.",),
            demo="v1_3_0"),
    Release("1.2.0", date(2026, 6, 2), "Pokladní doklad automaticky",
            ("Ke každé žádosti se rovnou vystaví pokladní doklad.",),
            demo="v1_2_0"),
    Release("1.1.0", date(2026, 5, 9), "Změna technických údajů",
            ("Nový typ žádosti a rychlý sken techničáku jedním klepnutím.",),
            demo="v1_1_0"),
    Release("1.0.0", date(2026, 3, 17), "Žádosti jsou tady",
            ("Vyfoť techničák a žádost o přepis vozidla se vyplní sama.",),
            demo="v1_0_0"),
)

CURRENT_RELEASE = RELEASES[0].version
