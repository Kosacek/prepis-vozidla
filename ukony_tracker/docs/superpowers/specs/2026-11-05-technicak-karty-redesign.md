# Spec: Sken techničáku — čistší karty výsledků (2.7.1)

**Pro:** evidence. Reakce Davida na demo 2.7 (2026-11-05).

## Proč (přesně jeho slova)

1. Souhrn nahoře ukazoval i nulové štítky (`Založeno 0`, `Doplněno 0`).
2. Sekce „Společná firma a typ pro všechna auta“ je zbytečná — **nikdy** nedělá
   dávku aut pro jednu firmu; fotí auta pro různé firmy a rozděluje je jednotlivě.
3. U duplicity je zbytečné třířádkové vysvětlování, co duplicita je — bold
   varování stačí.
4. Karty jednotlivých skenů jsou vizuálně přeplácané: hodně textu, všechno bold,
   málo hierarchie, špatně se hledá, co je důležité. David má rád řádky v
   `/ukony/vse` (screenshot): **barevná tečka firmy, tag typu, SPZ bold, VIN
   tlumeně, cena bold, platba jako barevný štítek, vzduch mezi sloupci**.
   ORV musí být na kartě výrazné (to je hlavní, co sken mění/přidává).

## Rozhodnutí

- **Souhrn**: vykreslit jen štítky s počtem > 0.
- **Bulk lišta pryč**: `#orv-batch` (firma/typ pro všechna + „Použít na všechna“)
  se z UI i JS odstraní. Každé auto má vlastní firmu + typ + poznámku.
- **Duplicita**: nadpis „Tohle auto už v evidenci je“ + existující úkon(y) +
  „Otevřít existující úkon“ + checkbox „Přesto založit nový úkon“. Žádný
  vysvětlující odstavec.
- **Karty ve stylu řádku Úkonů**:
  - levá malá fotka (56–64 px), pravá část s pevnou hierarchií:
    1. **status chip** malý (Založeno/Doplněno/Beze změny/Nové auto/Kontrola/Nečitelné),
    2. **RZ bold** (jako `.recent-rz`), vedle **tag typu** (`.tag`), vpravo
       **cena bold** (`.recent-kc`),
    3. **ORV** jako samostatný výrazný chip (`ORV UBP585612`) — hlavní údaj skenu;
       u chybějícího ORV červeně „ORV nepřečteno“,
    4. **řádek firmy**: barevná tečka (`.firma-dot` s barvou firmy) + zkratka
       firmy, u zakládaného auta místo toho selecty Firma/Typ + Poznámka,
    5. sekundární tlumený řádek: VIN, provozovatel (u nového auta), poznámka,
       změny `ORV staré → nové` (jen skutečně změněné), u beze změny nic.
    6. akce: malé tlačítko „Otevřít a upravit úkon“ (ne obří full-width),
       u nečitelného „Vyfotit znovu“ / „Přečíst znovu“.
  - žádné velké barevné rámy celé karty: stav jen úzký levý akcent / chip;
    karta = bílá, 1px border, radius 12, padding ~10–12, gap ~8.
  - fonty velikosti jako v řádcích: RZ 15–16 bold, tag 11, firma 13–14 600,
    VIN 13 tlumeně, cena 14–15 bold, poznámka/změny 12,5–13 tlumeně.
  - mobil ≤560 px: karta se skládá pod sebe, žádné horizontální přetečení.

## Kontrakt (backend → frontend)

- `_view(ukon)` vrací navíc `firma_id` (int) a `firma_zkratka` (str); platí pro
  `ukon`, `predchozi`, `existujici`, `kandidati`. Vytvořený `result.ukon` tyto
  klíče také má.
- `GET /ukony/orv-sken` předává do šablony `firmy` s barvou; šablona vloží
  `#orv-data` JSON:
  `{"ceny": {firma_id: {typ: cena}}, "firmy": [{"id","nazev","zkratka","color"}]}`.
- Zbytek kontraktu (stav, existujici, potvrdit_novy, poznamka) beze změny.

## Soubory

| Soubor | Změna |
|---|---|
| `services/orv_scan_service.py` | `_view`: firma_id + firma_zkratka; created ukon je má taky |
| `routes/orv_scan.py` | `fragment()`: barva firem do kontextu |
| `templates/_orv_sken.html` | pryč bulk lišta; `#orv-data` s firmami; stejné id kde to jde |
| `static/js/orv_report.js` | redesign karet, nonzero štítky, žádný bulk; bez duplicitního odstavce |
| `static/js/orv_sken.js` | pryč batch listenery/reset; payload beze změny |
| `static/css/orv_report.css` | nové kompaktní karty, firma tečky, tagy, mobil |
| `templates/base.html`, `templates/ukony_table.html` | `?v=` bumby |
| `releases.py` + `templates/demos/v2_7_1.html` | „Co je nového“ 2.7.1 |
| `tests/test_orv_report.cjs` | testy nového renderu/selection |
| `Dockerfile` | CACHEBUST |

## Co je nového 2.7.1

Titulek: „Sken techničáku je přehlednější“.
Body: „Každé auto má vlastní firmu, typ i poznámku — žádná společná lišta.“
„V kartách je hned vidět SPZ, ORV a firma; nulové souhrny se neschovávají za nuly.“
Demo: kompaktní karta s RZ/ORV/firmou (CSS only, ~4 s).
