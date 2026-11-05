# Spec: Nový doklad — IČO/ARES, skrytelné úkony, ruční vozidla (2.6)

**Pro:** evidence (`ukony_tracker/`) + malý zásah v žádostech (`prepis_app/`).
**Zadání Davida:** 2026-11-05 (Doklady → Nový doklad).

## Proč

1. Nový doklad dnes stojí na dvojici **firma → úkon**; bez úkonu doklad nevznikne.
   David chce umět vyplnit **IČO** a nechat si firmu (název + adresu) doplnit
   jako v žádostech (ARES), a vystavit doklad i bez úkonu.
2. Seznam nezaplacených úkonů firmy je dlouhý a nedá se sbalit — uživatel musí
   odscrollovat celý modal, aby se dostal k částce a tlačítku.
3. „Přijato od" se po změně IČO nemění (ARES se v dokladech vůbec nepoužívá,
   název jde jen z chipu plátce).
4. Když auto (RZ/VIN) není v evidenci, není kam ho napsat — doklad s autem,
   které v evidenci chybí, nejde vystavit.

## Rozhodnutí (David 2026-11-05)

- **Firma zůstává nepovinná.** Dvě cesty ve stejném modalu:
  (a) firma → zaškrtnout úkony (dosavadní), (b) IČO → ARES → název + adresa,
  bez úkonu (nová). Obě cesty jdou i zkombinovat.
- IČO lookup používá **ARES** (`GET /firmy/ares?ico=…`, už existuje). Automaticky
  po osmi číslicích (debounce ~450 ms) i tlačítkem; vyplní **Přijato od** a
  **Adresu**. Nezakládá novou firmu v evidenci.
- **Úkony** se vykreslí do sbalitelného panelu s hlavičkou
  „Nezaplacené úkony · N · X Kč"; tělo má vlastní scroll (max-height ~240 px),
  klik na hlavičku panel sbalí/rozbalí. Delší seznam (víc než 4 úkony) je po
  načtení sbalený, krátký otevřený — částka i tlačítko tak zůstanou na dosah.
  Zaškrtnuté úkony zůstávají i po sbalení.
- **Vozidla** jsou nové pole „Vozidla (RZ / VIN)". Předvyplní se z vybraných
  úkonů, dokud do něj uživatel nezasáhne (stejný princip jako částka); jde
  napsat i RZ/VIN, které v evidenci nejsou. Prázdné je povolené (doklad bez auta).
- **Adresa** je nové editovatelné pole „Adresa na doklad" (na PPD se tiskne pod
  jménem plátce). Priorita v žádostech: explicitní adresa z evidence → adresa
  strany žádosti (chip) → adresa uložené firmy podle IČO.
- Doklad bez úkonu: `ukony: []`, `firma_id` chybí/`null`. Firma dokladu pro filtr
  se dopočítá z `prijato_ico` (logika `ppd_links` už to umí).
- Platba se dál neoznačuje automaticky (beze změny).

## Kontrakt evidence → žádosti

`POST {ZADOSTI_API_URL}/api/ppd/vystavit`, `X-Api-Key`, nově:

```json
{"prijato_od": "JE & NE, spol. s r.o.",
 "prijato_ico": "44960263",
 "prijato_adresa": "Veveří 102, Brno, 616 00",   // NOVÉ, nepovinné, ≤200 znaků
 "castka": 2600,
 "ucel": "ZASTUPOVÁNÍ NA MMB",
 "vozidla": ["3BR9309", "TMBER6NW0V3099310"],    // NOVĚ smí být i prázdné (0–30)
 "zpracoval": "David",
 "request_id": "…",
 "zadost_id": "zad-a", "strana": "provozovatel"} // nepovinné, beze změny
```

Žádosti: `prijato_adresa` (text, ≤200, nesmí začínat `=`) má přednost před
adresou ze žádosti i z uložené firmy. `vozidla` smí být prázdný seznam → PPD
se vytiskne bez řádku SPZ/VIN. Číslování, `request_id` idempotence a záloha
beze změny.

## Kontrakt UI → evidence

`POST /doklady/novy`, JSON:

```json
{"firma_id": 3,                 // nepovinné; null/chybí = doklad bez firmy
 "ukony": [12, 14],             // 0–30; prázdné = doklad bez úkonu
 "prijato_od": "…", "prijato_ico": "44960263",
 "prijato_adresa": "…",         // nepovinné, ≤200
 "vozidla": ["3BR9309"],        // nepovinné; když chybí, odvodí se z úkonů
 "castka": 2600, "ucel": "…", "zpracoval": "David",
 "request_id": "…", "zadost_id": "…", "strana": "…"}
```

Validace evidence (`services/doklad_issue.validate`):
- `firma_id`: když je, musí existovat a být aktivní; když ne, nevadí.
- `ukony`: seznam intů 0–30; neprázdné úkony vyžadují `firma_id` a musí k ní
  patřit (jinak 400).
- `vozidla`: když je klíč přítomný, použije se přesně (i prázdný seznam);
  každé = text, velká písmena, bez vnitřních mezer navíc, ≤20 znaků, bez `=`
  na začátku, max 30, deduplikace; když klíč chybí, odvodí se z úkonů
  (`rz or vin`).
- `prijato_adresa`: text ≤200, ořezaný; prázdné = neposílat.
- `zadost_id`/`strana` dál jen pro vybrané úkony (plátce z žádosti).
- `castka` 1…10 000 000, `prijato_od` 1…120, `ucel` ≤80 — beze změny.

`GET /doklady/novy/ukony?firma=` vrací navíc `firma.adresa`, `firma.psc`
(pro předvyplnění adresy z uložené firmy).

## Soubory

| Soubor | Změna |
|---|---|
| `services/doklad_issue.py` | volitelná firma a úkony, `vozidla`, `prijato_adresa` |
| `templates/_doklad_new_modal.html` | nová pole + sbalitelný panel úkonů |
| `static/js/doklad_new.js` | ARES, sbalování, vozidla, adresa, payload |
| `static/js/doklad_payer.js` | adresa v chipu firmy + pure pomocníci (`adresaText`, `vozidlaFromUkony`, `parseVozidla`) |
| `routes/ppd.py` | `novy_ukony`: `adresa`/`psc` firmy |
| `static/css/app.css` | styly panelu/ARES/nových polí |
| `releases.py` + `templates/demos/v2_6.html` | „Co je nového" 2.6 |
| `tests/test_doklad_novy.py`, `tests/test_doklad_payer.cjs` | testy |
| `prepis_app/ppd_api.py` | `prijato_adresa`, prázdná `vozidla` |
| `prepis_app/tests/test_ppd_api.py` | testy |
| `prepis_app/{VERSION,version.py,app.py,Dockerfile}` | 1.31.0 |

## Co je nového 2.6

Titulek: „Doklad vyplníš z IČO".
Body: „Napiš IČO a jméno i adresa se doplní z ARES." / „Úkony firmy si sbalíš,
VIN nebo RZ můžeš napsat i ručně."

## Testy

- evidence: doklad bez úkonu projde a uloží se; ruční vozidla se pošlou místo
  odvozených; `prijato_adresa` se pošle; validace (0 úkonů bez firmy OK,
  úkony bez firmy 400, cizí firma 400, dlouhá/`=` adresa 400).
- JS: `adresaText`, `vozidlaFromUkony`, `parseVozidla`, adresa u chipu firmy.
- žádosti: `prijato_adresa` má přednost před žádostí i uloženou firmou;
  prázdná `vozidla` vystaví doklad bez SPZ/VIN; staré chování beze změny.
