# Spec: Barevné firmy, čistší karty skenu a editace nad techničákem (2.7.2)

**Pro:** evidence. Davidova zpětná vazba 2026-11-05 (po 2.7.1).

## Proč

1. Barevné tečky firem u výběru firmy v Úkonech se mu líbí — chce je **všude,
   kde se vybírá firma** (Doklady → Nový doklad, Techničák → karta auta).
2. U karty skenu je fotka vlevo nahoře; chce ji **vpravo nahoře**, aby byl
   text zarovnaný doleva (a rozklikávací náhled taky).
3. Cena na kartě zakládaného auta je nahoře u RZ a mate; patří **doprava dolů**
   vedle poznámky: řádek Firma + Typ, pod tím Poznámka (vlevo) + Cena (vpravo).
4. Placeholder „Poznámka k úkonu (nepovinná, max. 120)“ je zbytečný — pryč.
5. Hierarchie RZ → ORV → šedě VIN/provozovatel se mu líbí, zachovat.
6. „Otevřít a upravit úkon“ dnes **nahradí** obsah modalu (techničák zmizí).
   Chce, aby techničák zůstal a editace se otevřela **nad ním** s plynulým
   fade-in; po zavření se vrátí na techničák (bez rerenderu).

## Rozhodnutí

### 1. Sdílený barevný výběr firmy — `static/js/firma_pick.js`

Nový modul `window.FirmaPick` (vanilla, bez závislostí), jeden zdroj pravdy pro
výběr firmy s barevnou tečkou:

- API: `FirmaPick.attach(selectEl, opts)` → obalí nativní `<select>` (skryje ho
  jako dnes `.firma-pick.js > select`), vykreslí tlačítko + seznam s tečkami;
  chování a vzhled **shodné s `#firma-pick` v Úkonech** (app.css třídy
  `.firma-pick__*`, `.firma-dot`).
- Bere barvu z `option.dataset.color`; bez barvy šedá `var(--muted)`.
- Volba položky nastaví `select.value` a vyhodí `change` (bubbles), aby
  fungovaly stávající listenery (`loadUkony`, `photo.firmaOverride`, …).
- `FirmaPick.sync(selectEl)` překreslí tlačítko/seznam podle aktuální hodnoty
  (po `form.reset()`, po programové změně).
- `FirmaPick.refresh(selectEl)` znovu načte options (po dynamickém naplnění).
- Klávesy: Enter/Space otevírá, šipky pohyb, Esc zavírá; klik mimo zavře.
- Kde se použije:
  - **Doklady → Nový doklad**: `#dn-firma` (options s `data-color` z
    `firma_colors`; placeholder „— bez firmy —“). Po výběru dál funguje
    `loadUkony()`; po `form.reset()`/otevření `FirmaPick.sync`.
  - **Techničák**: `select.orv-card-firma` v každé kartě (options z hidden banky
    `#orv-firma-options`; banka musí mít `data-color` z `firmy_data`). `attach`
    po sestavení karty; změna vyhodí `change` → `photo.firmaOverride`.
- Bez JS zůstává nativní select funkční (stejně jako dnes v Úkonech).

### 2. Karta skenu — fotka vpravo, cena dole

- DOM: `body` první, `button.orv-card-preview` druhý; CSS grid
  `minmax(0,1fr) 58px` (na mobilu 46–52 px), fotka `align-self:start`.
- Cena v assign kartě: **pryč z řádku RZ**. Layout polí:
  - řádek 1: `Firma` (select s tečkou) + `Typ` (select),
  - řádek 2: `Poznámka` (input, flex) + `Cena` (label + bold částka vpravo),
  - pod tím tlumeně VIN / provozovatel.
- Poznámka: `placeholder="Poznámka"` (žádné „nepovinná, max. 120“).
- Written karty: cena zůstává vpravo na řádku RZ (jako v Úkonech); hierarchie
  RZ bold → typ tag → ORV chip → tečka+zkratka firmy → tlumené VIN/úkon/pozn.
- Issue karty: beze změny struktury, jen fotka vpravo.

### 3. Editace úkonu nad techničákem

- V `ukon_modal.js`: když je otevřený sken (`modal-card--scan`) a klikne se
  „Otevřít a upravit úkon“, **neodebírat** obsah skenu. Místo toho otevřít
  druhý overlay `.modal-stack` (fixed, scrim + karta, z-index nad `#ukon-modal`)
  s fetchnutým editačním formulářem. Fade-in ~200 ms (opacity + translateY
  scale), `prefers-reduced-motion` bez animace.
- Zavření (×, „Zpět“, Esc, klik na scrim) jen zavře stack s fade-out; sken
  zůstane přesně jak byl (scroll, výsledky). Po uložení: POST jako dnes,
  `ukon:saved` (karta dostane „✓ Upraveno“), stack se zavře, sken zůstane.
- Esc řeší nejdřív stack; klik na `data-modal-close` uvnitř stacku zavírá
  stack, ne celý sken. Ostatní chování (běžná editace bez skenu, nový úkon)
  beze změny.

### 4. Verze a popup

Release **2.7.2** „Firmy barevně a sken bez překážek“ (2 body + demo
`v2_7_2`): „Firmu vybereš s barevnou tečkou jako v Úkonech.“ / „Editace úkonu
se otevře nad techničákem; karta má fotku vpravo a cenu u poznámky.“

## Soubory

| Soubor | Změna |
|---|---|
| `static/js/firma_pick.js` | **nový** sdílený modul |
| `tests/test_firma_pick.cjs` | **nový** node test |
| `templates/_doklad_new_modal.html` | options `data-color`, placeholder |
| `static/js/doklad_new.js` | `FirmaPick.attach/sync` |
| `static/js/orv_report.js` | fotka vpravo, cena k poznámce, placeholder, FirmaPick v kartách |
| `templates/_orv_sken.html` | banka firem s `data-color` |
| `static/css/orv_report.css` | layout karty (grid, řádek poznámka+cena) |
| `static/js/ukon_modal.js` | stack overlay pro editaci nad skenem |
| `static/css/app.css` | `.modal-stack` + fade animace |
| `templates/base.html`, `templates/ukony_table.html`, `templates/doklady.html` | include `firma_pick.js` + `?v=` bumby |
| `releases.py` + `templates/demos/v2_7_2.html` | 2.7.2 |
| `Dockerfile` | CACHEBUST |

## Testy

- `test_firma_pick.cjs`: attach/sync/change dispatch, barvy z data-color, bez
  data-color šedá, refresh po změně options.
- `test_orv_report.cjs`: aktualizované karty (foto vpravo v DOM pořadí, cena
  v řádku poznámky, žádný dlouhý placeholder, RZ/ORV pořád stejné).
- Python beze změny (714).
- Browser e2e na demu: barvy v Dokladech i skenu, foto vpravo, cena u
  poznámky, editace nad techničákem s animací, po zavření sken zachován.
