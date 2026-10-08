# Spec: posílat pokladní doklady (PPD) do evidence

**Pro:** agenta, který vlastní zadosti.spznaklic.cz (`prepis_app/`).
**Od:** session evidence (Úkony Tracker), 2026-10-08, na Davidovo zadání.
**Stav:** strana evidence se staví teď (endpointy níže). Do `prepis_app/` session
evidence **nesahala** — jen tenhle soubor.

## Proč

David chce mít PPD na jednom místě s úkony — v evidenci. Tam je uvidí u úkonu,
v přehledu „Doklady" a hlavně je bude umět použít nový AI asistent „Zeptej se"
(„kolik hotovosti jsme vybrali v září", „doklady pro Albion"). zadosti si dál
vede svůj Excel (`ppd_evidence.xlsx` + `ppd_backup.xlsx`) — ten zůstává zdrojem
číslování a zálohou; evidence je kopie navíc. **Nic na číslování ani na Excelu
neměň.**

## Endpointy v evidenci (chráněné `X-Api-Key`, stejný klíč jako `/api/prichozi`)

```
PUT  /api/ppd/<cislo>        → 201 nový / 200 aktualizovaný nebo stejný (idempotentní)
POST /api/ppd/import         → {"doklady": [ ... ]}  hromadně, pro jednorázové doplnění
```
Tělo jednoho dokladu:
```json
{"cislo": 412, "datum": "08.10.2026", "prijato_od": "ALBION S.R.O.",
 "prijato_ico": "12345678", "castka": 1300, "ucel": "Zastupování na MMB",
 "vozidlo": "1AB2345", "zadost_id": "<stejné id jako v push žádosti>",
 "smazano": false}
```
Evidence si sama doklad spáruje s úkonem (přes `zadost_id`, jinak podle RZ/VIN
± 7 dní).

## Co udělat v zadosti

1. **Při vystavení PPD** (`app.py` kolem `ppd.reserve_ppd_number_and_log`) poslat
   `PUT /api/ppd/<cislo>` — **stejně jako `tracker_push`**: best-effort, na pozadí
   (`push_async`), nikdy neblokuje ani neshodí generování; při chybě do
   `failed_pushes.jsonl` (nebo vlastního `failed_ppd_pushes.jsonl`) a existující
   periodický `retry_failed` to dopošle. Idempotence je na straně evidence
   (PUT na stejné číslo = přepis), takže opakování je bezpečné.
   Pošli `zadost_id` stejný, jaký jde v push žádosti ve stejném requestu.
2. **Smazání PPD** (`delete_ppd`) → stejný PUT s `"smazano": true`.
   **Obnovení** (`restore_ppd_row`) → PUT s `"smazano": false`.
3. **Jednorázové doplnění historie** — skript (např.
   `scripts/ppd_do_evidence.py`), který přečte `read_backup()` (obsahuje i smazané)
   a živý ledger, nastaví `smazano` podle toho, jestli doklad v živém ledgeru je,
   a pošle vše jedním `POST /api/ppd/import` (po dávkách ~200). Spustit jednou na
   NASu po nasazení evidence. Výsledek (`vytvoreno`, `aktualizovano`, `chyby`)
   vypsat.
4. Testy: push při vystavení / smazání / obnovení (mock HTTP), selhání se zapíše
   k opakování, generování PPD funguje i když je evidence nedostupná.

## Pořadí nasazení

Evidence první (endpointy). Do té doby by zadosti dostala 404 — ber 404 jako
dočasnou chybu (zapsat k opakování), ne jako trvalý neúspěch.
