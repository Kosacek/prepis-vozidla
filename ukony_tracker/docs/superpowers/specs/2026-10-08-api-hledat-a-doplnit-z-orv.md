# Spec: API pro „Přidat do evidence" ze zadosti (hledat podle VIN + doplnit RZ/ORV)

**Pro:** agenta, který vlastní Úkony Tracker (evidence.spznaklic.cz).
**Od:** session zadosti.spznaklic.cz, 2026-10-08, na Davidovo zadání.
**Stav:** čeká na implementaci v trackeru. Strana zadosti je hotová a s tímto
API počítá — dokud endpointy neexistují (404), zadosti se chová, jako by se nic
nenašlo, a nabídne jen založení nového úkonu.

Do kódu trackeru zadosti session **nesahala** — jen tenhle soubor.

## Proč

Reálný postup v kanceláři: auto se nejdřív **zapisuje** (žádost o zápis má VIN,
RZ ještě neexistuje → úkon v evidenci vznikne s prázdnou RZ). Po registraci
přijde **ORV** (malý technický průkaz) s přidělenou RZ. Dnes se pak úkon v
evidenci ručně dohledává a RZ (a číslo ORV) se opisuje — přesně na to je
dnešní `/ukony/hledat` („locate a freshly registered car so its úkon can be
opened and the SPZ filled in").

Nově: v zadosti se naskenuje ORV a tlačítko **„Přidat do evidence"**:
1. najde úkony toho auta podle VIN,
2. jedním klikem doplní RZ + číslo ORV do úkonu, kde chybí,
3. když nic nenajde, založí nový úkon (to už jde přes existující `POST /api/ukony`).

## Endpoint 1 — hledání podle vozidla

```
GET /api/ukony/hledat?vin=<VIN>&rz=<RZ>
Header: X-Api-Key: <UKONY_API_KEY>      (stejná ochrana jako zbytek /api/*)
```

- Párování: **VIN, když je zadaný; jinak RZ** — stejná logika identity jako
  `ukony_repo.find_by_vehicle` (RZ se může přendat na jiné auto), ale **napříč
  všemi firmami** (find_by_vehicle je per-firma, tady firmu ještě neznáme).
- Porovnání bez ohledu na velikost písmen a mezery (`UPPER(TRIM(...))`).
- Seřazeno od nejnovějšího (`datum DESC, id DESC`), max **20**.
- Bez `vin` i `rz` → `400 {"error": "..."}`.

Odpověď `200`:
```json
{"ukony": [
  {"id": 1234, "datum": "2026-09-12", "firma_id": 3, "firma": "ALBION s.r.o.",
   "firma_zkratka": "ALB", "typ_kod": "ZÁPIS", "rz": null, "vin": "TMBEK6NW7M3158470",
   "orv": null, "celkem": 1300}
]}
```
Nic nenalezeno → `200 {"ukony": []}` (ne 404 — 404 si zadosti vykládá jako
„endpoint ještě neexistuje").

## Endpoint 2 — doplnění RZ / čísla ORV

```
POST /api/ukony/<id>/doplnit
Header: X-Api-Key: <UKONY_API_KEY>
Body:   {"rz": "1AB2345", "orv": "UBE037263"}     (obě pole volitelná, aspoň jedno)
```

Pravidla:
- **Doplňuje jen PRÁZDNÉ pole.** Nikdy nepřepíše existující hodnotu.
- Normalizace: `strip().upper()`, odstranit mezery a pomlčky.
- Validace: `rz` 5–8 znaků `[A-Z0-9]`; `orv` 3 písmena + 6 číslic (např.
  `UBE037263`). Jinak `400`.
- Když pole už má **jinou** hodnotu → nic nezapisovat, `409`:
  `{"error": "RZ už je vyplněná jinak.", "pole": "rz", "stavajici": "9ZZ9999"}`.
  Stejná hodnota → OK (idempotentní, `zmeneno` bez toho pole).
- Neexistující `id` → `404 {"error": "Úkon nenalezen."}`.
- Nic jiného se nemění (cena, stav platby, firma, datum…). Zápis přes
  `ukony_repo.update(conn, uid, rz=..., orv=...)` — `updated_at` se nastaví samo.
- POST → spustí se existující throttlovaný auto-backup v `before_request`
  (nic navíc).

Odpověď `200`:
```json
{"id": 1234, "rz": "1AB2345", "orv": "UBE037263", "zmeneno": ["rz", "orv"]}
```

## Testy, které by měly existovat (tracker)

1. hledání podle VIN najde úkony u různých firem, nejnovější první
2. VIN má přednost před RZ; bez obou → 400; nic nenalezeno → 200 + `[]`
3. bez / se špatným `X-Api-Key` → 401 (jako ostatní /api/*)
4. doplnění do prázdné RZ i ORV → 200, `zmeneno` obsahuje obě
5. RZ už vyplněná jinak → 409, DB beze změny
6. stejná hodnota podruhé → 200, nic se nezmění (idempotence)
7. neplatná RZ / ORV → 400; neexistující id → 404
8. cena, stav platby a datum zůstanou po doplnění stejné

## Strana zadosti (hotová, pro kontext)

- zadosti volá tyto endpointy jen ze serveru (klíč nikdy nejde do prohlížeče),
  přes svůj proxy `/api/evidence/hledat` a `/api/evidence/doplnit`.
- Na 404 z endpointu 1 → „hledání v evidenci zatím není k dispozici", nabídne
  jen nový úkon (`POST /api/ukony`, existuje).
- Na 409 z endpointu 2 → ukáže uživateli stávající hodnotu, nic nepřepisuje.

## Deploy

Standardně podle CLAUDE.md trackeru (jen kontejner `ukony-app`). Po nasazení
zadosti nic měnit nemusí — začne to fungovat samo.
