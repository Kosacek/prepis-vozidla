"""Version history of Žádosti (přepis vozidel), newest first.

Single source of truth for the "Co je nového" system (logic: novinky.py,
templates/_novinky.html, static/novinky.js). The newest entry pops up as a
card once per device after an update, then slides away into the sheet
"Co umí Žádosti", which lists only what the app can do NOW, in sections, each
with its demo. "Verze ⓘ" opens the sheet directly. Versions are the real app
versions (VERSION); patch releases are listed only when people would notice.

Adding a release (every user-visible update — see ../AGENTS.md): put a new
Release at the TOP when you bump VERSION. `title` is one short sentence in
user terms, at most two short `points`, Czech, informal "ty". `demo` names a
partial in templates/demos/ that shows the change in motion.

Classification (decides what the sheet shows):
  oblast     section key (see SEKCE in novinky.py); None = not on the sheet
  nahrazuje  older versions this release makes obsolete (they drop off)
  zastarale  no longer true / nothing to show: not on the sheet
  nazev      card title on the sheet (defaults to `title`)
  radek      one-line card text on the sheet (defaults to points[0])
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
    Release("1.35.1", date(2026, 11, 13), "Novinky na jedné stránce",
            ("Nejnovější změna vyskočí jako dřív a pod ní uvidíš všechno, co "
             "aplikace umí – bez starých verzí.",),
            oblast="formular",
            nazev="Novinky na jedné stránce",
            radek="Pod nejnovější změnou vidíš všechno, co aplikace umí – bez starých verzí."),
    Release("1.35.0", date(2026, 11, 13), "Jeden kód na všechno",
            ("Číslo faktury je zároveň kód: na zadosti.spznaklic.cz/5732 vytiskneš "
             "fakturu i všechny žádosti k ní.",
             "„Sdílet kódem“ kód obnoví na dalších 30 dní, pořád stejný."),
            demo="v1_35_0",
            oblast="sdileni", nahrazuje=("1.14.0", "1.18.0"),
            nazev="Jeden kód na všechno",
            radek="Číslo faktury je i kód: vytiskneš fakturu a všechny její žádosti."),
    Release("1.34.0", date(2026, 11, 13), "Doklad je teď vždy faktura s QR kódem",
            ("Zákazník zaplatí převodem nebo QR kódem a úkon se v evidenci sám "
             "označí jako zaplacený.",
             "Firmu v evidenci vybíráš s barevnou tečkou a návrhy poznámek "
             "naskočí přímo pod polem."),
            demo="v1_34_0",
            oblast="faktury", nahrazuje=("1.33.0", "1.21.0", "1.2.0"),
            nazev="Doklad je vždy faktura s QR",
            radek="Zákazník zaplatí převodem a evidence úkon sama označí."),
    Release("1.33.0", date(2026, 11, 13), "Doklad převodem i z žádosti",
            ("U dokladu přepneš Hotově / Převodem, šipkami i z klávesnice.",
             "Převodem se vystaví faktura s QR platbou a jde rovnou do evidence."),
            demo="v1_33_0",
            zastarale=True),  # volba Hotově/Převodem zrušena v 1.34.0
    Release("1.27.0", date(2026, 10, 26), "Zaseknutá kamera se vzpamatuje",
            ("Zamrzlý obraz se obnoví sám a po přepojení USB kamera naskočí "
             "bez klikání.",
             "Poznámky zase nabízejí, co jsi do nich psal dřív."),
            demo="v1_27_0",
            oblast="formular",
            nazev="Kamera se vzpamatuje",
            radek="Zamrzlý obraz se obnoví sám, i po přepojení USB."),
    Release("1.26.0", date(2026, 10, 23), "Žádost bez myši",
            ("Enter vyfotí ORV, vezme návrh a jde dál; Ctrl+Enter otevře "
             "všechny dokumenty k tisku. Zkratky ukáže klávesa ?.",
             "Kamera teď běží pořád, tak by už neměla zamrzat."),
            demo="v1_26_0",
            oblast="formular", nahrazuje=("1.19.0",),
            nazev="Žádost bez myši",
            radek="Enter vyfotí ORV a jde dál, Ctrl+Enter otevře dokumenty k tisku."),
    Release("1.25.0", date(2026, 10, 14), "Náhled před tiskem",
            ("Kód teď vždycky ukáže obrázek každého dokumentu, ať hned vidíš, "
             "že tiskneš ten správný.",
             "Plná moc k žádosti se přidá pod stejný kód."),
            demo="v1_25_0",
            oblast="sdileni",
            nazev="Náhled před tiskem",
            radek="Kód ukáže obrázek každého dokumentu, i plné moci."),
    Release("1.24.0", date(2026, 10, 13), "Zeptej se se doptá a navazuje",
            ("Napíšeš jméno firmy jen přibližně a nabídne ti tu správnou.",
             "Můžeš se ptát dál – třeba „a za říjen?“ – a ví, o čem je řeč."),
            demo="v1_24_0",
            oblast="hledani", nahrazuje=("1.23.0",),
            nazev="Zeptej se",
            radek="Ptej se normální větou a doptávej se dál."),
    Release("1.23.0", date(2026, 10, 13), "Hledání rozumí normální větě",
            ("Zeptej se třeba „Kolik převodů udělal Roman tento měsíc?“ – "
             "odpověď spočítá z tvých žádostí a dokladů.",
             "Kroky se plynule přesouvají a Doklady mají nový vzhled."),
            demo="v1_23_0",
            zastarale=True),  # hledání větou: novější znění v 1.24.0
    Release("1.22.0", date(2026, 10, 12), "Historie verzí",
            ("Klepni na číslo verze vlevo dole a uvidíš, co se kdy změnilo – "
             "listuješ šipkami nebo přejetím.",),
            demo="v1_22_0",
            zastarale=True),  # historii verzí nahrazuje přehled „Co umí Žádosti“
    Release("1.21.0", date(2026, 10, 9), "Doklady se samy propíšou do evidence",
            ("Každý vystavený pokladní doklad se pošle do evidence – i když ho "
             "smažeš nebo obnovíš.",),
            demo="v1_21_0",
            zastarale=True),  # pokladní doklady nahradila faktura (1.34.0)
    Release("1.20.0", date(2026, 10, 8), "Otočení kamery a nová Správa firem",
            ("Ikonou nebo klepnutím do náhledu otočíš obraz kamery o 180°.",
             "Správa firem má nový vzhled a uloženou firmu vybereš jen z klávesnice."),
            demo="v1_20_0",
            oblast="formular",
            nazev="Otočení kamery",
            radek="Ikonou nebo klepnutím do náhledu otočíš obraz o 180°."),
    Release("1.19.0", date(2026, 10, 8), "Plynulejší skenování",
            ("Sken techničáku už nepřeskakuje kroky a všechno vyplníš plynule "
             "z klávesnice.",),
            demo="v1_19_0",
            zastarale=True),  # skenování z klávesnice nahradila 1.26.0
    Release("1.18.0", date(2026, 10, 8), "Sdílecí kód všude",
            ("Sdílecí kód funguje i pro plnou moc, historii a Doklady.",
             "Kroky mají všude stejnou velikost."),
            demo="v1_18_0",
            zastarale=True),  # nahrazen jedním kódem 1.35.0
    Release("1.17.0", date(2026, 10, 8), "Rychlejší sken a rovnou do evidence",
            ("Sken používá novou, rychlejší AI.",
             "Hotovou žádost přidáš do evidence jedním tlačítkem."),
            demo="v1_17_0",
            oblast="evidence", nahrazuje=("1.3.22",),
            nazev="Do evidence jedním tlačítkem",
            radek="Hotovou žádost přidáš do evidence jedním tlačítkem."),
    Release("1.16.0", date(2026, 9, 30), "Plná moc i pro Romana",
            ("Plnou moc teď vystaví i Roman a přihlášení snese mezeru navíc.",),
            demo="v1_16_0",
            zastarale=True),  # drobnost, pokrývá plná moc 1.7.0
    Release("1.15.0", date(2026, 9, 21), "Rychlejší žádosti",
            ("Žádost se sestaví výrazně rychleji, i po delší pauze.",),
            demo="v1_15_0",
            zastarale=True),  # rychlost, není co ukázat
    Release("1.14.0", date(2026, 9, 18), "Krátký sdílecí odkaz",
            ("Žádost pošleš krátkým odkazem /1234 – otevře celý balík "
             "dokumentů přes celou obrazovku.",),
            demo="v1_14_0",
            zastarale=True),  # nahrazen jedním kódem 1.35.0
    Release("1.11.0", date(2026, 9, 16), "Správné datum na tiskopisu",
            ("Datum se řídí úředními hodinami přepážky, ne automaticky zítřkem.",),
            demo="v1_11_0",
            oblast="formular",
            nazev="Správné datum na tiskopisu",
            radek="Datum se řídí úředními hodinami přepážky."),
    Release("1.10.0", date(2026, 9, 15), "Náhled faktury a víc vozidel",
            ("Fakturu si před vystavením prohlédneš a přidáš na ni další vozidla.",),
            demo="v1_10_0",
            oblast="faktury",
            nazev="Náhled faktury a víc vozidel",
            radek="Fakturu si před vystavením prohlédneš a přidáš na ni další vozidla."),
    Release("1.9.0", date(2026, 9, 2), "Chytřejší propojení s evidencí",
            ("Firma se páruje podle IČO, i z prodávajícího, a evidence zná "
             "elektrické značky.",),
            demo="v1_9_0",
            oblast="evidence",
            nazev="Firma podle IČO",
            radek="Firma se páruje podle IČO a evidence zná elektrické značky."),
    Release("1.8.0", date(2026, 9, 1), "Filtry v hledání",
            ("Hledání má naklikávací filtry a měsíc zadáš číslem.",),
            demo="v1_8_0",
            oblast="hledani", nahrazuje=("1.3.32",),
            nazev="Filtry v hledání",
            radek="Naklikáš filtry a měsíc zadáš číslem."),
    Release("1.7.0", date(2026, 8, 31), "Čistší plná moc",
            ("Nezaškrtnutá RZ nebo VIN se na papír vůbec nevytiskne.",),
            demo="v1_7_0",
            oblast="typy", nahrazuje=("1.5.0", "1.16.0"),
            nazev="Plná moc",
            radek="Nezaškrtnutá RZ nebo VIN se na papír nevytiskne."),
    Release("1.6.0", date(2026, 8, 11), "Žádost na vývoz",
            ("Nový typ žádosti: vývoz vozidla. První krok má volby vedle sebe.",),
            demo="v1_6_0",
            oblast="typy",
            nazev="Žádost na vývoz",
            radek="První krok má volby vedle sebe."),
    Release("1.5.0", date(2026, 8, 9), "Plná moc",
            ("Vystavíš plnou moc k zastupování na registru vozidel.",),
            demo="v1_5_0",
            zastarale=True),  # plná moc: novější znění v 1.7.0
    Release("1.4.0", date(2026, 8, 8), "Tabulka s registrační značkou",
            ("V Ostatních úkonech je nová žádost o tabulku s RZ.",),
            demo="v1_4_0",
            oblast="typy",
            nazev="Tabulka s RZ",
            radek="V Ostatních úkonech je nová žádost o tabulku."),
    Release("1.3.32", date(2026, 8, 3), "Hledání",
            ("Najdeš žádosti, doklady i firmy na jednom místě – bez hrabání na NAS.",),
            demo="v1_3_32",
            zastarale=True),  # základní hledání: pokrývá 1.8.0
    Release("1.3.22", date(2026, 7, 11), "Úkon do evidence rovnou ze žádosti",
            ("Na poslední stránce vybereš firmu, typ a cenu a úkon se zapíše "
             "do evidence.",),
            demo="v1_3_22",
            zastarale=True),  # novější znění v 1.17.0
    Release("1.3.13", date(2026, 6, 15), "Tisk jedním klepnutím",
            ("Žádost se vytiskne jedním klepnutím, doklad rovnou na A5.",),
            demo="v1_3_13",
            oblast="sdileni",
            nazev="Tisk jedním klepnutím",
            radek="Žádost se vytiskne jedním klepnutím."),
    Release("1.3.0", date(2026, 6, 2), "Vystavené doklady",
            ("Seznam všech vystavených faktur s hledáním.",),
            demo="v1_3_0",
            oblast="faktury",
            nazev="Seznam faktur",
            radek="Všechny vystavené faktury s hledáním na jednom místě."),
    Release("1.2.0", date(2026, 6, 2), "Pokladní doklad automaticky",
            ("Ke každé žádosti se rovnou vystaví pokladní doklad.",),
            demo="v1_2_0",
            zastarale=True),  # pokladní doklad: teď faktura (1.34.0)
    Release("1.1.0", date(2026, 5, 9), "Změna technických údajů",
            ("Nový typ žádosti a rychlý sken techničáku jedním klepnutím.",),
            demo="v1_1_0",
            oblast="typy",
            nazev="Změna technických údajů",
            radek="Samostatný typ žádosti."),
    Release("1.0.0", date(2026, 3, 17), "Žádosti jsou tady",
            ("Vyfoť techničák a žádost o přepis vozidla se vyplní sama.",),
            demo="v1_0_0",
            oblast="formular",
            nazev="Vyfoť techničák",
            radek="Žádost o přepis se vyplní sama z fotky."),
)

CURRENT_RELEASE = RELEASES[0].version
