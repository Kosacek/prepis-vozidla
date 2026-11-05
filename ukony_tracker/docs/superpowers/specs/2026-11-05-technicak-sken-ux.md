# Spec: Sken techničáku — jedno zadání firmy, poznámka, přefocení a guard na duplicity (2.7)

**Pro:** evidence (`ukony_tracker/`). Žádosti se nemění.
**Zadání Davida:** 2026-11-05 (Úkony → Techničák).

## Proč

Davidovy výtky k dnešnímu skenu:

1. Po vyfocení nového auta se ptá na firmu **dvakrát** (společná firma v dávce +
   firma u každého auta), i když je v dávce jen jedno auto. Nechápe proč.
2. **Nejde napsat poznámka** k zakládanému úkonu.
3. Je to „hassle“ poznat, co se přidává, kam se to zapíše a jak to pak upravit.
4. Nečitelná fotka nabízí jen „Zkusit znovu“, což **znovu pošle tutéž fotku**;
   chybí vyfotit novou.
5. Chybové hlášky a stavy nejsou akční (co udělat dál), není vidět, co se
   přečetlo a co chybí.
6. **Duplicita RZ 1AKI647 (3. 11. 2026).** V produkci jsou dva úkony téhož auta:
   `#1537` 27. 10. PŘEVOD, zdroj `zadosti`, zaplaceno, ORV `UBM028053`;
   `#1573` 3. 11. NOVÉ, zdroj `orv_sken`, nezaplaceno, ORV `UBP585023`.
   Sken našel VIN/RZ, ale protože šlo o kompletní úkon starší než
   `MATCH_WINDOW_DAYS` (1 den), vyhodnotil ho jako „jiný prodej“ a po potvrzení
   v dávce založil druhý úkon. Uživatel si toho nevšiml — varování „Dříve …“
   bylo malé a snadno přehlédnutelné.

## Rozhodnutí

- **Firma se zadává jednou.** Společná lišta (firma + typ) se zobrazí jen když
  je k doplnění **2 a více** aut. Jedno auto = jeden karta s firmou, typem
  a poznámkou. U víc aut jde každé auto přepsat (override) a tlačítko
  „Použít na všechna“ nastaví společnou volbu.
- **Poznámka** je nové nepovinné pole u každého zakládaného auta (max 120 znaků);
  uloží se do `ukony.poznamka` stejně jako v ručním formuláři.
- **Přefocení:** u nečitelné/chybové fotky je primární akce **„Vyfotit znovu“**
  (nativní foťák / výběr souboru) — nová fotka **nahradí** tu starou v kartě
  a hned se přečte. „Přečíst znovu“ (stejná fotka) zůstává jen u přechodné
  chyby (spojení, AI nedostupná), ne u nečitelného dokumentu.
- **Guard proti duplicitám:** když ke skenu existuje stejné auto (VIN/RZ) v
  evidenci mimo okno automatického doplnění, výsledek nese `existujici`
  (id, datum, firma, typ, cena, stav platby, poznámka) a **server odmítne
  založit nový úkon**, dokud klient nepošle `potvrdit_novy: true`. UI ukáže
  velké varování s odkazem „Otevřít existující úkon“ a zaškrtávátko
  „Přesto založit nový úkon“. Tím se 1AKI647 už nemůže stát bez vědomého
  potvrzení.
- **Stav `jiz_v_evidence`** (nový) = auto má starší úkon; karta zůstává
  v sekci k doplnění, dokud uživatel nepotvrdí (nebo neotevře existující úkon).
- **Jasné výsledky:** každá karta napíše, co se přečetlo (RZ/VIN/ORV + zdroj
  VIN), co se zapsalo (změny před→po), do kterého úkonu (`#id`, firma, typ,
  cena) a má výrazné **„Otevřít a upravit úkon“**. Souhrn má štítky
  Hotovo / Ke kontrole.
- **Kroky:** `1 · Foť` → `2 · Zpracovávám` → `3 · Zkontroluj a doplň`
  (jen když je co řešit) → `4 · Hotovo`.
- **Cena u karty:** fragment předá mapu cen (firma × typ), karta u zakládaného
  auta ukáže „Cena: 1 300 Kč“ podle zvolené firmy a typu.

## Kontrakty

### `GET /ukony/orv-sken` (fragment)

Nově dostane `ceny`: `{ "<firma_id>": {"<typ_kod>": 1300.0 | null}, … }` pro
všechny aktivní firmy (`pricing_service.firm_price_map`). Šablona je vloží jako
JSON blok `#orv-data` vedle stávajících `<select>`ů (ty zůstávají fallback).

### `POST /ukony/orv-sken` (výsledek fotky)

`result` navíc:

```json
{"stav": "bez_firmy",
 "predchozi": {"id": 1537, "datum": "2026-10-27", "firma": "JE & NE",
               "typ": "PŘEVOD", "celkem": 1300.0,
               "stav_platby": "zaplaceno", "poznamka": "ACC"},
 "existujici": [ … 1–5 stejných tvarů, nejnovější první … ],
 "vyzaduje_potvrzeni": true}
```

`_view()` se rozšíří o `stav_platby` a `poznamka` (stávající klíče zůstávají).
U `vice_shod` přibude `kandidati`: seznam `_view` (max 5) úkonů, mezi kterými
se má vybrat; u `konflikt` se `kandidati` doplní, když jich je víc.

### `POST /ukony/orv-sken/zalozit`

```json
{"zpracoval": "David",
 "auta": [{"rz": "1AKI647", "vin": "…", "orv_cislo": "…",
           "provozovatel": "…", "vin_zdroj": "foto",
           "firma_id": 14, "typ_kod": "NOVÉ",
           "poznamka": "ACC",              // NOVÉ, nepovinné, ≤120
           "potvrdit_novy": false}]}       // NOVÉ, nepovinné, bool
```

Validace navíc: `poznamka` text ořezaný ≤120 (jinak 400); `potvrdit_novy` bool.
Výsledek pro auto, které má `existujici` a `potvrdit_novy` není `true`:

```json
{"stav": "jiz_v_evidence", "existujici": […],
 "ukon": {"id": 1537, …},   // existující úkon pro odkaz
 "zprava": "Toto auto už má úkon #1537 z 27. 10. 2026 (PŘEVOD, JE & NE). Potvrď „Přesto založit nový úkon“."}
```

Nic se nezaloží. S `potvrdit_novy: true` se založí nový úkon (jako dnes) a do
`ukony.poznamka` se uloží poznámka.

## UI

Sekce výsledku (`orv_report.js`) se přeskupí:

1. **Souhrn**: banner („Vše v pořádku“ / „Zkontroluj N aut“) + štítky
   `✚ Založeno`, `✎ Doplněno`, `✓ Beze změny`, `⚠ Ke kontrole`, `✗ Nečitelné`.
2. **Ke kontrole a doplnění** (`#orv-assign`): karty pro `bez_firmy`,
   `jiz_v_evidence`, `necitelne`, `chyba`, `konflikt`, `vice_shod`,
   `nenalezeno`; u zakládaných aut foto, přečtené údaje, firma, typ,
   poznámka, cena, varování u existujícího úkonu + potvrzovací checkbox.
   Společná lišta jen při ≥2 autech.
3. **Zapsáno** (`#orv-results`): karty hotových (založeno/doplněno/beze změny)
   s `#id`, firmou, typem, cenou, poznámkou a tlačítkem
   **„Otevřít a upravit úkon“**; u doplnění změny před→po.
4. Skrytý `#orv-retake` file input (`capture=environment`) pro přefocení.

Karta auta k doplnění (JS): checkbox pro výběr? Ne — všechna auta se zakládají
najednou tlačítkem „Založit N úkonů“; potvrzovací checkbox jen u duplicit.
Tlačítko se počítá jen z aut, která mají firmu+typ a (u duplicity) potvrzení.

## Soubory

| Soubor | Změna |
|---|---|
| `services/orv_scan_service.py` | `existujici`, `jiz_v_evidence`, `kandidati`, poznámka, potvrzení |
| `routes/orv_scan.py` | validace `poznamka`/`potvrdit_novy`, `ceny` do fragmentu |
| `templates/_orv_sken.html` | sekce, skrytý retake input, JSON data (ceny) |
| `static/js/orv_report.js` | přepis karet: fronta/kontrola/zapsáno, poznámka, cena, duplicity, odkazy |
| `static/js/orv_sken.js` | přefocení, payload poznámky/potvrzení, kroky, počítání |
| `static/css/orv_report.css` | nové karty, varování, pole, mobil |
| `templates/ukony_table.html` | `?v=` bumby skriptů |
| `releases.py` + `templates/demos/v2_7.html` | „Co je nového“ 2.7 |
| `tests/test_orv_scan.py`, `tests/test_orv_create.py`, `tests/test_orv_report.cjs` | testy |
| `Dockerfile` | CACHEBUST |

## Co je nového 2.7

Titulek: „Techničák víc pod kontrolou“.
Body: „Firmu a typ vybereš u auta — a konečně můžeš napsat poznámku.“
„Nečitelnou fotku vyfotíš znovu; když už auto v evidenci je, sken se zeptá,
než založí druhý úkon.“

## Doplňky při integraci (Lead, 2026-11-05)

- Tlačítka „Vyfotit další“ / „Zavřít“ se během kontroly (`reviewPhotos > 0`)
  **skryjí** — jedno omylem trefené tlačítko by zahodilo rozdělané firmy
  a poznámky. Když kontrola zbývá, zavírání křížkem se **ptá** („Něco ještě
  není doplněné…“). Po dořešení se tlačítka vrátí a krok je `4 · Hotovo`.
- Na mobilu se tlačítka v kartě duplicity zalamují (`white-space: normal`,
  `min-width: 0`) — jinak přetékala šířku karty a text se ořezával.

## Testy

- scan: úkon mimo okno → `existujici` + `predchozi` (staré beze změny);
  `zalozit` bez potvrzení → `jiz_v_evidence`, žádný insert; s potvrzením →
  nový úkon + poznámka; kandidáti u `vice_shod`; `_view` má stav platby.
- route: `poznamka` ≤120 (delší 400), `potvrdit_novy` bool, ceny ve fragmentu.
- report (node): nové seskupení, výpočet tlačítka s duplicitami, poznámka
  v payloadu, texty karet.
- ruční e2e v prohlížeči: nečitelná fotka → „Vyfotit znovu“ → nová fotka se
  přečte; duplicita → varování → potvrzení → založí; poznámka se uloží.
