# Spec: přestavba Dokladů (PPD) v evidenci — verze 2.5

**Pro:** session evidence (Úkony Tracker). Část „Nový doklad" potřebuje endpoint v žádostech
(viz níže), ten zadává koordinátor session žádostí.
**Schváleno:** David 2026-10-26 podle vizuálního návrhu
https://claude.ai/artifact/4BTPVuB4VjHvb3TE44M1qE

## Proč

- Řádky dokladů nemají pevné sloupce: vozidlo a tlačítko „Úkon #…" mají pokaždé jinou šířku,
  na mobilu tlačítko přeskakuje mezi řádky. Nesedí s designem Úkonů.
- Doklad s víc auty (č. 179: 5 aut) se nepřiřadí k žádnému úkonu.
- Doklad, který přijde dřív než jeho úkon (č. 180, 182), se později už nepřiřadí.
- Chybí filtr firmy a hledání jako v Úkonech.
- David chce vystavit doklad přímo z evidence.
- Na iPhonu se prázdný výběr měsíce (`<input type="month">`) vykreslí jako tečka.

## Rozhodnutí Davida (2026-10-26)

1. Nový doklad začíná **výběrem úkonů** firmy (nezaplacené), částka/auta/plátce se předvyplní.
2. Platba se **neoznačuje sama**. Nezaplacený úkon, ke kterému patří doklad, má **oranžové
   „Zaplatit"** s číslem dokladu; uživatel platbu potvrdí klepnutím, úkon po úkonu.
3. Firma dokladu pro filtr = **firma jeho úkonů**; bez úkonu podle IČO plátce (`firmy.ico`).
4. Ruční oprava přiřazení **zatím ne**; nenalezené auto se v rozbaleném dokladu ukáže červeně.

## Přiřazení doklad ↔ úkony (`services/ppd_links.py`)

Počítá se při každém vykreslení (ne jen při příchodu dokladu), pro všechny nesmazané doklady.

1. **Explicitní vazby** (tabulka `ppd_ukony(ppd_cislo, ukon_id)`, PK obou): doklady vystavené
   z evidence. Mají přednost a platí bez ohledu na datum.
2. **zadost_id** dokladu → `prichozi.created_ukon_id` (jako dnes).
3. **Vozidla:** `ppd.vozidlo` se rozdělí podle `,` `;` a konců řádků; každá položka bez mezer,
   velkými písmeny = RZ nebo VIN. Kandidáti = úkony s tímto RZ nebo VIN a datem v okně
   **±14 dní** od data dokladu (reálná data: úkon −2 až +6 dní). Víc kandidátů → nejbližší
   datem; shoda v datu → ten, jehož `celkem` = `castka` dokladu (doklad s jedním autem), jinak
   všichni shodní.
4. Výsledek: `doklad → [úkony]`, `doklad → [nenalezená auta]`, `úkon → [čísla dokladů]`.
   Sloupec `ppd.ukon_id` zůstává (zpětná kompatibilita, AI nástroj), ale UI ho nepoužívá.

Na záloze z 26. 10.: 125 → 128 přiřazených dokladů ze 156; č. 179 → #1323, #1325, #1326,
#1348, #1349; č. 180 → #1470; č. 182 → #1486.

**Firma dokladu:** firma, ke které patří většina jeho úkonů; bez úkonů firma s `ico` =
`prijato_ico`; jinak žádná („—").

## Stránka Doklady (`/doklady`)

- Hlavička: „Doklady" + tlačítko **+ Nový doklad**.
- Filtr stejný jako v Úkonech: živé hledání (číslo, přijato od, RZ, VIN, firma),
  **Všechny firmy**, měsíc, Platné/Smazané, „Vše". Filtruje se okamžitě v prohlížeči,
  počet a součet se přepočítají (dokladů je ~160, načtou se všechny).
- Řádek (počítač): `č. | datum | ● firma | přijato od | auta (štítky, max 2 + „+N") |
  částka | N úkonů / bez úkonu | ▸`. Pevné šířky, nic neskáče.
- Řádek (mobil, ≤760 px): `č. … částka` / `● firma · datum · plátce` / štítky aut /
  `N úkonů ▾`.
- Klepnutí kamkoli na doklad ho rozbalí (akordeon, `aria-expanded`), pod ním jeho úkony
  ve stejném partialu jako v Úkonech (`_ukony_item.html`), nenalezená auta červeně, patička
  „Úkony celkem X Kč · doklad Y Kč" (✓ když sedí). Klepnutí na úkon otevře jeho úpravu.
- Smazaný doklad: přeškrtnuté číslo + štítek „smazaný", jen při filtru Smazané.

## Oranžové „Zaplatit"

`_stav_slot.html`: nezaplacený úkon s alespoň jedním dokladem dostane třídu `pay-doklad`
(barvy existujícího warn: `#fff0ce` / `#754600` / okraj `#d98a00`), title „Doklad č. N —
potvrď platbu"; mobilní popisek „Zaplatit · doklad č. N". Platí na /ukony/vse, „Tento měsíc"
a v rozbaleném dokladu. AJAX odpověď na platbu vrací stejný partial (mapa vazeb se předá).

## Nový doklad

Modal (stejný styl jako Nový úkon): Firma → seznam jejích nezaplacených úkonů bez dokladu
(posledních 90 dní) se zaškrtnutím → Přijato od (název + IČO firmy, přepsatelné) → Účel
(„ZASTUPOVÁNÍ NA MMB") → Částka (součet, přepsatelná) → **Vystavit doklad**.

Server evidence (`POST /doklady/novy`, session) zavolá žádosti (viz kontrakt), uloží vrácený
doklad přes `ppd_repo.upsert`, zapíše explicitní vazby do `ppd_ukony` a vrátí odkaz na tisk
`https://zadosti.spznaklic.cz/ppd-print/<cislo>`. Když žádosti endpoint nemají (404) nebo
neodpoví, modal ukáže srozumitelnou chybu a nic se neuloží.

### Kontrakt pro žádosti

`POST {ZADOSTI_API_URL}/api/ppd/vystavit`, hlavička `X-Api-Key` = sdílený klíč integrace
(žádosti: `UKONY_API_KEY`, evidence: `INTEGRATION_API_KEY`).

```json
{"prijato_od": "JE & NE, SPOL. S R.O.", "prijato_ico": "44960263",
 "castka": 2600, "ucel": "ZASTUPOVÁNÍ NA MMB",
 "vozidla": ["3BR9309", "3BR7164"], "zpracoval": "David",
 "request_id": "6f1c2a1e-6b1d-4c55-9a3e-2f0a9d1b7c44"}
```

Žádosti udělají totéž co při vystavení dokladu u žádosti: `reserve_ppd_number_and_log`,
`build_ppd_pdf`, `append_backup`, push do evidence. Odpověď `201`:
`{"doklad": <stejný záznam jako PUT /api/ppd>, "print_url": "/ppd-print/<cislo>"}`.
`request_id` (doplněno na žádost koordinátora): jedno id na doklad, evidence ho vytvoří při otevření
dialogu a při opakování posílá stejné. Pro už použité `request_id` vrátí žádosti `200` se stejným
dokladem (žádné nové číslo); evidence bere `200` i `201` jako úspěch.
Chyby: `400 {"error"}`, `401` špatný klíč. Evidence potřebuje env `ZADOSTI_API_URL`
(`http://zadosti-app:8089`).

## iPhone: výběr měsíce

Všechny `input[type=month]` (Doklady, Úkony, zadávání): pevná `min-height`/`min-width`
jako ostatní filtry, `::-webkit-date-and-time-value { text-align:left; min-height:1.2em }`,
a když je prázdný, viditelný popisek „Všechny měsíce" (překryv přes pole). Ověřit na
skutečném iPhonu (Davidův).

## Co je nového 2.5

Demo: řádek č. 179 se rozbalí a vyjede 5 úkonů, jeden s oranžovým „Zaplatit".
Titulek „Doklady ukážou, co platí"; body: rozbalení s úkony + oranžové Zaplatit; nový
doklad z evidence.

## Testy

- `ppd_links`: dělení vozidel, okno ±14, nejbližší datum, shoda částky při remíze,
  explicitní vazby, zadost_id, firma dokladu, nenalezená auta, smazané doklady se nepočítají.
- Stránka: filtr firmy, živé hledání atributy, akordeon, oranžové tlačítko jen u
  nezaplacených s dokladem.
- Nový doklad: validace, volání žádostí (mock), uložení + vazby, chyba 404/timeout nic neuloží.
