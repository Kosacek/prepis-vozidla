# Přepis Vozidla — Project Context

## What This Project Is

A local Flask web app that automates filling Czech vehicle transfer forms. The user runs it on their Windows PC, opens it in a browser at `http://localhost:5050`, fills in a 5-step form, and gets two filled PDFs ready to print.

The person using this is a freelancer/autobazar worker who processes 5–20 vehicle ownership transfers (přepisy) per day, always at the úřad in Brno.

---

## How To Run

```bash
pip install flask pypdf requests
python app.py
# → open http://localhost:5050
```

---

## Project Structure

```
prepis_app/
├── app.py                  # Flask backend — all logic lives here
├── templates/
│   └── index.html          # Full single-page UI (5-step wizard)
├── pdfs/
│   ├── zmeny.pdf           # Template: Žádost o zápis změny vlastníka (3 pages, 72 fields)
│   └── zapis.pdf           # Template: Žádost o zápis do registru (2 pages, 57 fields)
├── output/                 # Generated PDFs saved here (auto-created)
└── CONTEXT.md              # This file
```

---

## What The App Does (User Flow)

1. **Step 1** — Choose transfer type + set city (default: Brně)
2. **Step 2** — Enter prodávající (seller) data — fyzická or právnická osoba. Can scan a document (camera/upload) → Claude Vision extracts data automatically. Can also type IČO → ARES API auto-fills company name/address.
3. **Step 3** — Enter kupující (buyer) data — same options as Step 2
4. **Step 4** — Enter vehicle data (VIN, RZ, značka, barva, etc.). Can scan COC list or Osvědčení → auto-fills vehicle fields.
5. **Step 5** — Review summary → Generate PDFs → Download / Print

---

## The Two PDF Forms

### 1. zmeny.pdf — "Žádost o zápis změny vlastníka nebo provozovatele silničního vozidla"
- 3 pages, 72 fillable fields
- Page 1: Dosavadní vlastník (seller), Dosavadní provozovatel (if different), checkboxes for what changes
- Page 2: Mezitímní vlastník (usually blank), Nový vlastník (buyer), Nový provozovatel (if different)
- Page 3: Záznam registračního místa — LEFT BLANK (filled by the úřad)

### 2. zapis.pdf — "Žádost o zápis silničního vozidla do registru silničních vozidel"
- 2 pages, 57 fillable fields
- Page 1: Vlastník (= buyer/kupující), Provozovatel (if different)
- Page 2: Technický popis vozidla (VIN, kategorie, druh, typ, značka, barva checkboxes), Účel využití

---

## Critical PDF Field Mappings

### zmeny.pdf field map (key fields):

| Field ID | Meaning |
|---|---|
| `comb_1` | Registrační značka (RZ) — comb, 7 chars |
| `comb_2` | VIN — comb, 17 chars |
| `Druh vozidla` | Druh vozidla (text) |
| `fill_2` | Dosavadní vlastník — jméno (line 1) |
| `comb_3` | Dosavadní vlastník — RČ před lomítkem (6 digits) |
| `undefined` | Dosavadní vlastník — RČ za lomítkem (4 digits) |
| `comb_5` | Dosavadní vlastník — IČO (8 digits) |
| `osoby 1` | Dosavadní vlastník — adresa |
| `fill_5` | Dosavadní vlastník — PSČ |
| `fill_6` | Dosavadní provozovatel — jméno (blank if same as owner) |
| `comb_6` | Dosavadní provozovatel — RČ před lomítkem |
| `undefined_2` | Dosavadní provozovatel — RČ za lomítkem |
| `comb_8` | Dosavadní provozovatel — IČO |
| `osoby 1_2` | Dosavadní provozovatel — adresa |
| `vlastníka` | Checkbox: změna vlastníka |
| `provozovatele` | Checkbox: změna provozovatele |
| `vlastníka i provozovatele` | Checkbox: změna obojího |
| `V` | Místo podpisu (page 1) |
| `dne` | Datum (page 1) |
| `fill_1` | Mezitímní vlastník — jméno (usually blank) |
| `comb_1_2` | Mezitímní vlastník — IČO |
| `fill_8` | Nový vlastník — jméno |
| `comb_5_2` | Nový vlastník — RČ před lomítkem |
| `undefined_4` | Nový vlastník — RČ za lomítkem |
| `comb_7` | Nový vlastník — IČO |
| `osoby 1_3` | Nový vlastník — adresa |
| `fill_11` | Nový vlastník — PSČ |
| `fill_12` | Nový provozovatel — jméno (blank if same as new owner) |
| `V_3` | Místo podpisu (page 2) |
| `dne_3` | Datum (page 2) |

### zapis.pdf field map (key fields):

| Field ID | Meaning |
|---|---|
| `Text3` | Vlastník (kupující) — jméno |
| `comb_3` | Vlastník — RČ před lomítkem (6 digits) |
| `undefined` | Vlastník — RČ za lomítkem (4 digits) |
| `comb_5` | Vlastník — IČO (8 digits) |
| `osoby` | Vlastník — adresa |
| `fill_2` | Vlastník — PSČ |
| `fill_3` | Provozovatel — jméno (blank if same as owner) |
| `comb_6` | Provozovatel — RČ před lomítkem |
| `undefined_2` | Provozovatel — RČ za lomítkem |
| `comb_8` | Provozovatel — IČO |
| `V` | Místo podpisu |
| `dne` | Datum |
| `comb_1_2` | VIN — comb, 17 chars |
| `Text12` | Kategorie vozidla (e.g. M1) |
| `Text6` | Druh vozidla |
| `Text7` | Typ vozidla |
| `Text8` | Značka a obchodní označení |
| `Check Box13` | Barva: bílá |
| `Check Box14` | Barva: žlutá |
| `Check Box15` | Barva: oranžová |
| `Check Box16` | Barva: červená |
| `Check Box17` | Barva: fialová |
| `Check Box18` | Barva: modrá ✓ |
| `Check Box19` | Barva: zelená |
| `Check Box20` | Barva: šedá |
| `Check Box21` | Barva: hnědá |
| `Check Box22` | Barva: černá |
| `undefined_4` | Číslo technického průkazu — LEFT BLANK intentionally |
| `fill_6_2` | Číslo schválení technické způsobilosti |
| `vozidlo taxislužby` | Checkbox účel — always False |
| `toggle_2` | Checkbox účel — always False |
| `toggle_3` | Checkbox účel — always False |
| `vozidlo obecného užití` | Checkbox účel — always True |
| `V_2` | Místo podpisu (page 2) |
| `dne_2` | Datum (page 2) |

---

## Critical PDF Technical Notes

### Czech Diacritics Fix
Must set `NeedAppearances = True` in the AcroForm dictionary. Without this, Czech characters (á, é, í, ó, ú, ů, č, ř, š, ž, ď, ť, ň) render as garbage in image preview but display correctly in real PDF viewers (Chrome, Acrobat, Edge).

### Checkbox On-Values
- `zmeny.pdf` checkboxes use `/On` as the checked value (standard)
- `zapis.pdf` color checkboxes (Check Box13–22) use `/Ano` as the checked value (non-standard Czech PDF)
- The `fill_pdf()` function handles this dynamically by reading the `/AP/N` stream keys

### Comb Fields
Fields with `Ff=25165824` are comb fields — each character goes into a separate box. They work the same as text fields, just set the value as a plain string and the PDF renders it character by character automatically.

### fill_pdf() Function
The core function that fills both PDFs. It:
1. Reads the template PDF
2. Appends it to a writer
3. Sets NeedAppearances=True
4. Iterates all annotations across all pages
5. For buttons (/Btn): dynamically finds the correct on-value via /_States_ or /AP/N keys
6. For text fields: uses TextStringObject for proper Unicode encoding
7. Returns bytes

---

## Hardcoded Business Rules

These are intentional and should NOT be changed without user confirmation:

| Rule | Value | Reason |
|---|---|---|
| Default city | `Brně` | Always signing at Brno úřad |
| Date | Tomorrow's date | Forms are always signed next day |
| Účel využití | Always `vozidlo obecného užití` | Never taxi/půjčovna/přednost |
| Číslo TP (`undefined_4`) | Always blank | Left for úřad to stamp |

---

## APIs Used

### ARES (Czech Business Registry)
- URL: `https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}`
- Free, official, no auth needed
- Returns: obchodniJmeno, sidlo (nazevUlice, cisloDomovni, nazevObce, psc)
- Used for: auto-filling company name/address when IČO is entered

### Anthropic Claude API (Vision/OCR)
- Model: `claude-haiku-4-5-20251001` (cheapest, fast, sufficient for OCR)
- Used for: scanning physical documents (COC list, Osvědčení, OP, Plná moc)
- Returns: structured JSON with person/vehicle data
- Cost: ~$0.01–0.03 per scan
- API key stored in `app.py` line 17 — replace with new key if needed

---

## Data Model (what gets passed to build_*_fields)

```python
{
    # Parties
    "prodavajici_jmeno": str,    # Seller full name or company name
    "prodavajici_adresa": str,   # Seller address (street + city)
    "prodavajici_psc": str,      # Seller postal code
    "prodavajici_rc_1": str,     # Seller RČ before slash (6 digits)
    "prodavajici_rc_2": str,     # Seller RČ after slash (3-4 digits)
    "prodavajici_ico": str,      # Seller IČO (8 digits, blank if fyzická osoba)

    "kupujici_jmeno": str,
    "kupujici_adresa": str,
    "kupujici_psc": str,
    "kupujici_rc_1": str,
    "kupujici_rc_2": str,
    "kupujici_ico": str,

    # Vehicle
    "vin": str,                  # 17-char VIN
    "registracni_znacka": str,   # SPZ e.g. "1AB2345"
    "druh_vozidla": str,         # e.g. "osobní automobil"
    "kategorie_vozidla": str,    # e.g. "M1"
    "typ_vozidla": str,          # type code
    "znacka": str,               # brand + model e.g. "Škoda Octavia"
    "barva_vozidla": str,        # one of: bila/zluta/oranzova/cervena/fialova/modra/zelena/seda/hneda/cerna
    "cislo_schvaleni": str,      # číslo schválení technické způsobilosti

    # Transfer type (zmeny.pdf only)
    "zmena_vlastnika": bool,
    "zmena_provozovatele": bool,
    "zmena_oboji": bool,

    # Location (overrides default "Brně")
    "misto": str,
}
```

---

## Known Issues / Future Work

- [ ] **Scan feature not yet tested** — built and wired up, needs real-world testing with actual document photos
- [ ] **API key should be moved to .env file** — currently hardcoded in app.py line 17
- [ ] **No input validation** — fields are not validated before PDF generation
- [ ] **Output folder accumulates files** — no cleanup of old generated PDFs
- [ ] **Phase 3 ideas**: Justice.cz company verification, SQLite history of past transfers, saved frequent parties (e.g. the dealership itself)

---

## Tech Stack

- Python 3.x
- Flask (web server + routing)
- pypdf (PDF form filling)
- requests (ARES API + Anthropic API)
- Vanilla HTML/CSS/JS (no framework, single-file template)
