from flask import Flask, render_template, request, jsonify, send_file
import requests
import json
import os
from dotenv import load_dotenv
import sys as _sys
_base = getattr(_sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_base, '.env'))
import io
import base64
from PIL import Image
from datetime import datetime
from pypdf import PdfReader, PdfWriter
import openpyxl

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = "prepis-vozidla-secret-2024"

import sys
import shutil
BASE_DIR = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

try:
    with open(os.path.join(BASE_DIR, 'VERSION')) as _vf:
        __version__ = _vf.read().strip()
except Exception:
    from version import __version__

# Writable data dir — NAS when reachable, else %APPDATA%/PrepisVozidla when frozen, else next to app.py
NAS_DATA_DIR = r"\\192.168.1.18\Petr\PrepisVozidla\data"
if os.path.isdir(NAS_DATA_DIR):
    DATA_DIR = NAS_DATA_DIR
elif getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PrepisVozidla")
else:
    DATA_DIR = BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

# ── Migrate data from old location (data/ next to exe) ──────────────────────
if getattr(sys, 'frozen', False):
    _old_data_dir = os.path.join(os.path.dirname(sys.executable), "data")
    _migrated_marker = os.path.join(_old_data_dir, "_migrated")
    if os.path.isdir(_old_data_dir) and not os.path.exists(_migrated_marker):
        for item in os.listdir(_old_data_dir):
            src = os.path.join(_old_data_dir, item)
            dst = os.path.join(DATA_DIR, item)
            if not os.path.exists(dst):
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        try:
            with open(_migrated_marker, "w") as f:
                f.write("migrated")
        except OSError:
            pass

PDF_ZMENY = os.path.join(BASE_DIR, "pdfs", "zmeny.pdf")
PDF_ZAPIS = os.path.join(BASE_DIR, "pdfs", "zapis.pdf")
FIRMY_XLSX = os.path.join(DATA_DIR, "firmy.xlsx")
PLNE_MOCE_DIR = os.path.join(DATA_DIR, "plne_moce")
SCANS_DIR = os.path.join(DATA_DIR, "scans")
os.makedirs(PLNE_MOCE_DIR, exist_ok=True)
os.makedirs(SCANS_DIR, exist_ok=True)

# ── Excel helpers ─────────────────────────────────────────────────────────────
def _load_firmy_wb():
    if os.path.exists(FIRMY_XLSX):
        return openpyxl.load_workbook(FIRMY_XLSX)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Firmy"
    ws.append(["Název", "IČO", "Adresa", "PSČ", "ID"])
    wb.save(FIRMY_XLSX)
    return wb

def save_firmy(firms: list):
    firms = sorted(firms, key=lambda f: f.get("nazev", "").lower())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Firmy"
    ws.append(["Název", "IČO", "Adresa", "PSČ", "ID"])
    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 8
    ws.column_dimensions["E"].width = 14
    for f in firms:
        ws.append([f.get("nazev",""), f.get("ico",""), f.get("adresa",""), f.get("psc",""), f.get("id","")])
    wb.save(FIRMY_XLSX)

def read_firmy() -> list:
    wb = _load_firmy_wb()
    ws = wb.active
    firms = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] or row[1]:
            ico = str(row[1] or "")
            firms.append({
                "nazev": row[0] or "", "ico": ico,
                "adresa": row[2] or "", "psc": str(row[3] or ""),
                "id": str(row[4] or "") if len(row) > 4 else "",
                "has_plna_moc": os.path.exists(os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf")),
            })
    return firms

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODELS = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

# ── Claude Vision scan ────────────────────────────────────────────────────────
SCAN_PROMPT = """Analyze this Czech vehicle document image and extract all data.
Return ONLY valid JSON with no explanation or markdown fences.

Extract these fields (use null if not found):
{
  "jmeno": "full name or company name",
  "adresa": "street and city combined",
  "psc": "postal code 5 digits",
  "rc_1": "rodne cislo before slash 6 digits",
  "rc_2": "rodne cislo after slash 3-4 digits",
  "ico": "ICO 8 digits",
  "vin": "VIN 17 characters",
  "registracni_znacka": "SPZ plate",
  "druh_vozidla": "vehicle type e.g. osobni automobil",
  "kategorie_vozidla": "category e.g. M1",
  "typ_vozidla": "type code",
  "znacka": "brand and model e.g. Skoda Octavia",
  "barva_vozidla": "color: bila/zluta/oranzova/cervena/fialova/modra/zelena/seda/hneda/cerna",
  "cislo_schvaleni": "cislo schvaleni technicke zpusobilosti",
  "document_type": "coc or osveceni or plna_moc or op or other"
}"""

ORV_SCAN_PROMPT = """You are reading one or more Czech vehicle documents. Extract all available data and return ONLY valid JSON — no explanation, no markdown fences.

DOCUMENT TYPES YOU MAY SEE:

1. ORV — "Osvědčení o registraci vozidla" (green/white card, Part I or Part II)
   - "C.1.1. a C.1.2. PROVOZOVATEL" or "VLASTNÍK" section → person name
   - "C.1.3. ADRESA POBYTU / SÍDLO" → street + house number + city (WITHOUT postal code)
   - Postal code (PSČ) is a separate 5-digit number — it may appear at the END of the address line (e.g. "NA STRÁNI 412, HLADKÉ ŽIVOTICE, 742 47") — strip it from adresa and put it only in psc
   - "(A) REGISTRAČNÍ ZNAČKA VOZIDLA" at the top right → RZ plate, 7-8 chars e.g. "8T25415"
   - Red large number at bottom e.g. "UBE 037263" → osvedceni_serie = first 3 chars, osvedceni_cislo = last 6 digits (ignore space)
   - DO NOT extract RČ from ORV — ORV only shows datum narození, not rodné číslo. Set rc_1 and rc_2 to null.
   - "C.4. PROVOZOVATEL JE VLASTNÍKEM VOZIDLA" ANO → same_as_vlastnik: true
   - VIN may be on Part II only — set null if not visible

2. COC list (Certificate of Conformity) — printed A4, EU format
   - "Vehicle Identification Number (E)" → VIN
   - "Make (D.1)" → brand
   - "Type (D.2)" ONLY — do NOT include Variant (D.3) or Version (D.4)
   - "Category (J)" → M1 etc.
   - "Colour of vehicle (R)" → barva
   - No owner data on COC

3. OP (Občanský průkaz) — Czech ID card
   - "Příjmení", "Jméno", "Datum narození", address
   - RČ only from OP (format XXXXXX/XXXX) → rc_1 = 6 digits before slash, rc_2 = digits after slash

4. Plná moc — ignore, no data to extract

CRITICAL RULES:
- adresa must NEVER contain the PSČ — strip any 5-digit postal code from the end of address
- psc is always exactly 5 digits
- rc_1 and rc_2 are null unless you see an explicit RČ with a "/" slash (not from ORV)
- osvedceni_serie + osvedceni_cislo come from the large red number on ORV (e.g. "UBE 037263" → serie="UBE", cislo="037263")
- registracni_znacka is always 7-8 characters, letters and digits only
- Return null for any field not found — never guess

Return this exact JSON structure:
{
  "vlastnik": {
    "jmeno": "surname + first name, or company name",
    "adresa": "street + house number + city — NO postal code here",
    "psc": "5-digit postal code only",
    "rc_1": null,
    "rc_2": null,
    "ico": "8-digit company ID or null",
    "datum_narozeni": "DD.MM.YYYY or null"
  },
  "provozovatel": {
    "jmeno": null,
    "adresa": null,
    "psc": null,
    "rc_1": null,
    "rc_2": null,
    "ico": null,
    "same_as_vlastnik": true
  },
  "vin": "17 characters or null",
  "registracni_znacka": "7-8 char plate or null",
  "druh_vozidla": "osobni automobil / nakladni automobil / motocykl / pripojne vozidlo / autobus / traktor",
  "kategorie_vozidla": "M1 / N1 etc. or null",
  "typ_vozidla": "D.2 Typ code only, never include variant or version",
  "znacka": "brand + model e.g. Škoda Octavia",
  "barva_vozidla": "bila/zluta/oranzova/cervena/fialova/modra/zelena/seda/hneda/cerna",
  "cislo_schvaleni": "type approval number or null",
  "osvedceni_serie": "3 letters from red ORV number e.g. UBE",
  "osvedceni_cislo": "6 digits from red ORV number e.g. 037263"
}"""

def rotate_180(image_b64: str, mime_type: str) -> str:
    img_bytes = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(img_bytes))
    img = img.rotate(180)
    buf = io.BytesIO()
    fmt = "JPEG" if "jpeg" in mime_type or "jpg" in mime_type else "PNG"
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def _has_data(result: dict) -> bool:
    if not result.get("success"):
        return False
    data = result.get("data", {})
    return bool(data.get("spz") or data.get("vin") or data.get("znacka"))

def scan_document(image_b64: str, mime_type: str, model: str = "sonnet") -> dict:
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODELS.get(model, MODELS["sonnet"]),
                "max_tokens": 800,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}},
                        {"type": "text", "text": SCAN_PROMPT}
                    ]
                }]
            },
            timeout=30
        )
        if response.status_code != 200:
            return {"success": False, "error": f"API HTTP {response.status_code}: {response.text[:200]}"}
        result = response.json()
        if "error" in result:
            return {"success": False, "error": result["error"].get("message", "API error")}
        text = result["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        return {"success": True, "data": json.loads(text.strip())}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}

# ── ARES lookup ──────────────────────────────────────────────────────────────
def lookup_ico(ico: str) -> dict:
    ico = "".join(c for c in ico.strip() if c.isdigit())[:8].zfill(8)
    try:
        url = f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
        r = requests.get(url, timeout=8, headers={"Accept": "application/json"})
        if r.status_code == 200:
            d = r.json()
            sidlo = d.get("sidlo", {})
            ulice = sidlo.get("nazevUlice", "")
            domovni = str(sidlo.get("cisloDomovni", "")) if sidlo.get("cisloDomovni") else ""
            orientacni = str(sidlo.get("cisloOrientacni", "")) if sidlo.get("cisloOrientacni") else ""
            cislo = f"{domovni}/{orientacni}" if domovni and orientacni else domovni or orientacni
            adresa = f"{ulice} {cislo}".strip() if ulice else cislo
            obec = sidlo.get("nazevObce", "")
            if obec and adresa:
                adresa_full = f"{adresa}, {obec}"
            else:
                adresa_full = adresa or obec
            return {
                "success": True,
                "ico": ico,
                "nazev": d.get("obchodniJmeno", ""),
                "adresa": adresa_full,
                "psc": str(sidlo.get("psc", "")),
                "pravni_forma": d.get("pravniForma", ""),
            }
    except Exception:
        pass
    return {"success": False, "error": "Subjekt nenalezen nebo chyba spojení"}

# ── PDF filling helpers ───────────────────────────────────────────────────────
def fill_pdf(template_path: str, field_map: dict) -> bytes:
    from pypdf.generic import NameObject, BooleanObject, TextStringObject
    NO_UPPER = {'V', 'V_2', 'V_3', 'V_4', 'dne', 'dne_2', 'dne_3', 'dne_4'}
    reader = PdfReader(template_path)
    writer = PdfWriter()
    writer.append(reader)
    if '/AcroForm' in writer._root_object:
        writer._root_object['/AcroForm'].update({NameObject('/NeedAppearances'): BooleanObject(True)})
    for page in writer.pages:
        if '/Annots' not in page:
            continue
        for annot in page['/Annots']:
            annot_obj = annot.get_object()
            if annot_obj.get('/Subtype') != '/Widget':
                continue
            field_name = annot_obj.get('/T')
            if not field_name or str(field_name) not in field_map:
                continue
            val = field_map[str(field_name)]
            ft = annot_obj.get('/FT')
            if ft == '/Btn':
                states = annot_obj.get('/_States_', [])
                on_val = next((s for s in states if str(s) not in ('/Off', '/No')), None)
                if not on_val:
                    ap = annot_obj.get('/AP', {})
                    if ap:
                        ap_obj = ap.get_object() if hasattr(ap, 'get_object') else ap
                        n = ap_obj.get('/N', {})
                        if n:
                            n_obj = n.get_object() if hasattr(n, 'get_object') else n
                            on_val = next((k for k in n_obj.keys() if k not in ('/Off', '/No')), None)
                on_val = on_val or '/On'
                v = NameObject(on_val) if val else NameObject('/Off')
                annot_obj.update({NameObject('/V'): v, NameObject('/AS'): v})
            else:
                text = str(val) if str(field_name) in NO_UPPER else str(val).upper()
                annot_obj.update({NameObject('/V'): TextStringObject(text)})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

def add_id_overlay(pdf_bytes: bytes, overlays: list) -> bytes:
    """overlays: list of (page_index, x, y, text)"""
    import io as _io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from pypdf import PdfReader as _R, PdfWriter as _W

    # Build overlay PDF
    overlay_buf = _io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=A4)

    # Group overlays by page
    pages_needed = max(o[0] for o in overlays) + 1
    for page_idx in range(pages_needed):
        page_overlays = [o for o in overlays if o[0] == page_idx]
        if page_overlays:
            c.setFont("Helvetica", 8)
            for _, x, y, text in page_overlays:
                tw = stringWidth(text, "Helvetica", 8)
                c.drawString(x - tw, y, text)  # right-align to x
        c.showPage()
    c.save()
    overlay_buf.seek(0)

    # Merge overlay onto filled PDF
    from pypdf.generic import NameObject, BooleanObject
    base = _R(stream=_io.BytesIO(pdf_bytes))
    overlay_reader = _R(stream=overlay_buf)
    writer = _W()
    writer.append(base)
    for i, page in enumerate(writer.pages):
        if i < len(overlay_reader.pages):
            page.merge_page(overlay_reader.pages[i])
    # Ensure NeedAppearances is preserved
    if '/AcroForm' in writer._root_object:
        writer._root_object['/AcroForm'].update({NameObject('/NeedAppearances'): BooleanObject(True)})
    out = _io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()

def _next_working_day() -> str:
    from datetime import timedelta
    d = datetime.now()
    d += timedelta(days=1)
    # If landed on Saturday (5) go to Monday; if Sunday (6) go to Monday
    if d.weekday() == 5:
        d += timedelta(days=2)
    elif d.weekday() == 6:
        d += timedelta(days=1)
    return d.strftime("%d.%m.%Y")

def build_zmeny_fields(data: dict) -> dict:
    tomorrow = _next_working_day()
    misto = "Brně"

    # Dosavadní provozovatel — use jiný prov if checked, otherwise same as původní vlastník
    if data.get("puvodni_prov_jiny"):
        dos_prov_jmeno  = data.get("puvodni_prov_jmeno", "")
        dos_prov_rc_1   = data.get("puvodni_prov_rc_1", "")
        dos_prov_rc_2   = data.get("puvodni_prov_rc_2", "")
        dos_prov_ico    = data.get("puvodni_prov_ico", "")
        dos_prov_adresa = data.get("puvodni_prov_adresa", "")
        dos_prov_psc    = data.get("puvodni_prov_psc", "")
    else:
        dos_prov_jmeno  = data.get("puvodni_jmeno", "")
        dos_prov_rc_1   = data.get("puvodni_rc_1", "")
        dos_prov_rc_2   = data.get("puvodni_rc_2", "")
        dos_prov_ico    = data.get("puvodni_ico", "")
        dos_prov_adresa = data.get("puvodni_adresa", "")
        dos_prov_psc    = data.get("puvodni_psc", "")

    # Nový provozovatel — use jiný prov if checked, otherwise same as nový vlastník
    if data.get("novy_prov_jiny"):
        novy_prov_jmeno  = data.get("novy_prov_jmeno", "")
        novy_prov_rc_1   = data.get("novy_prov_rc_1", "")
        novy_prov_rc_2   = data.get("novy_prov_rc_2", "")
        novy_prov_ico    = data.get("novy_prov_ico", "")
        novy_prov_adresa = data.get("novy_prov_adresa", "")
        novy_prov_psc    = data.get("novy_prov_psc", "")
    else:
        novy_prov_jmeno  = data.get("novy_jmeno", "")
        novy_prov_rc_1   = data.get("novy_rc_1", "")
        novy_prov_rc_2   = data.get("novy_rc_2", "")
        novy_prov_ico    = data.get("novy_ico", "")
        novy_prov_adresa = data.get("novy_adresa", "")
        novy_prov_psc    = data.get("novy_psc", "")

    fields = {
        # Vehicle
        "Druh vozidla": data.get("druh_vozidla", ""),
        "comb_1":       data.get("registracni_znacka", ""),
        "comb_2":       data.get("vin", ""),

        # Dosavadní vlastník
        "fill_2":   data.get("puvodni_jmeno", ""),
        "Text1":    "",
        "comb_3":   data.get("puvodni_rc_1", ""),
        "undefined": data.get("puvodni_rc_2", ""),
        "comb_5":   data.get("puvodni_ico", ""),
        "osoby 1":  data.get("puvodni_adresa", ""),
        "osoby 2":  "",
        "fill_5":   data.get("puvodni_psc", ""),

        # Dosavadní provozovatel
        "fill_6":     dos_prov_jmeno,
        "Text2":      "",
        "comb_6":     dos_prov_rc_1,
        "undefined_2": dos_prov_rc_2,
        "comb_8":     dos_prov_ico,
        "osoby 1_2":  dos_prov_adresa,
        "osoby 2_2":  "",
        "fill_9":     dos_prov_psc,

        # Žádá o změnu checkboxes
        "vlastníka":                 data.get("zmena_vlastnika", False),
        "provozovatele":             data.get("zmena_provozovatele", False),
        "vlastníka i provozovatele": data.get("zmena_oboji", False),

        # Podpis page 1
        "V":   misto,
        "dne": tomorrow,

        # Mezitímní vlastník (always blank)
        "fill_1":   "",
        "Text3":    "",
        "comb_1_2": "",
        "fill_2_2": "",
        "fill_3":   "",
        "fill_4":   "",
        "V_2":      "",
        "dne_2":    "",

        # Nový vlastník
        "fill_8":      data.get("novy_jmeno", ""),
        "Text4":       "",
        "comb_5_2":    data.get("novy_rc_1", ""),
        "undefined_4": data.get("novy_rc_2", ""),
        "comb_7":      data.get("novy_ico", ""),
        "osoby 1_3":   data.get("novy_adresa", ""),
        "osoby 2_3":   "",
        "fill_11":     data.get("novy_psc", ""),

        # Nový provozovatel
        "fill_12":     novy_prov_jmeno,
        "Text5":       "",
        "comb_2_2":    novy_prov_rc_1,
        "undefined_3": novy_prov_rc_2,
        "comb_4":      novy_prov_ico,
        "osoby 1_4":   novy_prov_adresa,
        "osoby 2_4":   "",
        "fill_15":     novy_prov_psc,

        # Podpis page 2
        "V_3":   misto,
        "dne_3": tomorrow,

        # Page 3 — osvedceni + jiny doklad + podpis zadatele
        # undefined_5/fill_2_3 = Technický průkaz; fill_3_2/fill_4_2 = Osvědčení o registraci vozidla
        "fill_3_2":     data.get("osvedceni_serie", ""),
        "fill_4_2":     data.get("osvedceni_cislo", ""),
        "fill_5_2":     data.get("jiny_doklad", ""),  # first line of "Jiný doklad k silničnímu vozidlu" at top
        "V_4":   misto,
        "dne_4": tomorrow,
    }
    return fields

def build_zapis_fields(data: dict) -> dict:
    tomorrow = _next_working_day()
    misto = "Brně"

    color_map = {
        "bila":     "Check Box13",
        "zluta":    "Check Box14",
        "oranzova": "Check Box15",
        "cervena":  "Check Box16",
        "fialova":  "Check Box17",
        "modra":    "Check Box18",
        "zelena":   "Check Box19",
        "seda":     "Check Box20",
        "hneda":    "Check Box21",
        "cerna":    "Check Box22",
    }
    color_fields = {v: False for v in color_map.values()}
    selected_color = data.get("barva_vozidla", "")
    if selected_color in color_map:
        color_fields[color_map[selected_color]] = True

    # Provozovatel — use jiný prov if checked, otherwise same as nový vlastník
    if data.get("novy_prov_jiny"):
        prov_jmeno  = data.get("novy_prov_jmeno", "")
        prov_rc_1   = data.get("novy_prov_rc_1", "")
        prov_rc_2   = data.get("novy_prov_rc_2", "")
        prov_ico    = data.get("novy_prov_ico", "")
        prov_adresa = data.get("novy_prov_adresa", "")
        prov_psc    = data.get("novy_prov_psc", "")
    else:
        prov_jmeno  = data.get("novy_jmeno", "")
        prov_rc_1   = data.get("novy_rc_1", "")
        prov_rc_2   = data.get("novy_rc_2", "")
        prov_ico    = data.get("novy_ico", "")
        prov_adresa = data.get("novy_adresa", "")
        prov_psc    = data.get("novy_psc", "")

    fields = {
        # Vlastník (nový / kupující)
        "Text3":     data.get("novy_jmeno", ""),
        "comb_3":    data.get("novy_rc_1", ""),
        "undefined": data.get("novy_rc_2", ""),
        "comb_5":    data.get("novy_ico", ""),
        "osoby":     data.get("novy_adresa", ""),
        "fill_2":    data.get("novy_psc", ""),

        # Provozovatel
        "fill_3":      prov_jmeno,
        "fill_6":      "",
        "comb_6":      prov_rc_1,
        "undefined_2": prov_rc_2,
        "comb_8":      prov_ico,
        "fill_7":      prov_adresa,
        "fill_5":      prov_psc,

        # Odevzdání dokladů
        "Text1":  "",
        "Text2":  "",
        "Text9":  "",
        "Text10": "",

        # Místo / datum page 1
        "V":   misto,
        "dne": tomorrow,

        # VIN + vehicle tech data (page 2)
        "comb_1_2": data.get("vin", ""),
        "Text12":   data.get("kategorie_vozidla", ""),
        "Text6":    data.get("druh_vozidla", ""),
        "Text7":    data.get("typ_vozidla", ""),
        "Text8":    data.get("znacka", ""),

        **color_fields,

        "undefined_4": "",
        "fill_6_2":    data.get("cislo_schvaleni", ""),

        "fill_7_2": "VOZIDLO BYLO ŘÁDNĚ ZAKOUPENO A ZAPLACENO DPH",
        "fill_8_2": data.get("poznamky", "").strip(),
        "fill_9":   "",
        "fill_10":  "",

        "vozidlo taxislužby":    False,
        "toggle_2":              False,
        "toggle_3":             False,
        "vozidlo obecného užití": True,

        # Podpis page 2 
        "V_2":   misto,
        "dne_2": tomorrow,
    }
    return fields

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    from flask import make_response
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/api/firmy", methods=["GET"])
def api_firmy_get():
    return jsonify(read_firmy())

@app.route("/api/firmy", methods=["POST"])
def api_firmy_add():
    f = request.json or {}
    ico = "".join(c for c in str(f.get("ico","")).strip() if c.isdigit())
    nazev = str(f.get("nazev","")).strip()
    if not ico or not nazev:
        return jsonify({"success": False, "error": "Chybí IČO nebo název"})
    firms = read_firmy()
    firm_id = "".join(c for c in str(f.get("id","")).strip() if c.isdigit())[:10]
    if not any(x["ico"] == ico for x in firms):
        firms.append({"nazev": nazev, "ico": ico, "adresa": str(f.get("adresa","")).strip(), "psc": str(f.get("psc","")).strip(), "id": firm_id})
        save_firmy(firms)
    return jsonify({"success": True})

@app.route("/api/firmy/<ico>", methods=["DELETE"])
def api_firmy_delete(ico):
    ico = "".join(c for c in ico.strip() if c.isdigit())
    # Also remove plná moc if exists
    pm_path = os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf")
    if os.path.exists(pm_path):
        os.remove(pm_path)
    firms = [f for f in read_firmy() if f["ico"] != ico]
    save_firmy(firms)
    return jsonify({"success": True})

@app.route("/api/firmy/<ico>/plna-moc", methods=["POST"])
def api_plna_moc_upload(ico):
    ico = "".join(c for c in ico.strip() if c.isdigit())
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "Žádný soubor"})
    f = request.files['file']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({"success": False, "error": "Pouze PDF"})
    f.save(os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf"))
    return jsonify({"success": True})

@app.route("/api/firmy/<ico>/plna-moc", methods=["DELETE"])
def api_plna_moc_delete(ico):
    ico = "".join(c for c in ico.strip() if c.isdigit())
    pm_path = os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf")
    if os.path.exists(pm_path):
        os.remove(pm_path)
    return jsonify({"success": True})

@app.route("/plna-moc/<ico>")
def serve_plna_moc(ico):
    ico = "".join(c for c in ico.strip() if c.isdigit())
    pm_path = os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf")
    if not os.path.exists(pm_path):
        return "Not found", 404
    return send_file(pm_path, mimetype="application/pdf")

@app.route("/api/ico", methods=["POST"])
def api_ico():
    ico = request.json.get("ico", "")
    return jsonify(lookup_ico(ico))

_DRUH_MAP = {
    "OSOBNÍ AUTOMOBIL":   "osobni automobil",
    "NÁKLADNÍ AUTOMOBIL": "nakladni automobil",
    "MOTOCYKL":           "motocykl",
    "PŘÍPOJNÉ VOZIDLO":   "pripojne vozidlo",
    "AUTOBUS":            "autobus",
    "TRAKTOR":            "traktor",
}

def lookup_orv(serie: str, cislo: str) -> dict:
    api_key = "AqyAq8Z46PtuzEEX6yBevKDItydri1F1"
    orv = (serie.strip() + cislo.strip()).upper()
    try:
        r = requests.get(
            "https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2",
            params={"orv": orv},
            headers={"api_key": api_key},
            timeout=8,
        )
        resp = r.json()
        if r.status_code == 200 and resp.get("Status") == 1 and resp.get("Data"):
            d = resp["Data"]
            typ_raw = d.get("Typ", "")
            typ = typ_raw.split(" / ")[0].strip() if " / " in typ_raw else typ_raw
            znacka = " ".join(filter(None, [d.get("TovarniZnacka", ""), d.get("ObchodniOznaceni", "")])).strip()
            druh_raw = (d.get("VozidloDruh") or "").upper()
            druh = _DRUH_MAP.get(druh_raw, druh_raw.lower())
            return {
                "success":           True,
                "vin":               d.get("VIN", ""),
                "typ_vozidla":       typ,
                "znacka":            znacka,
                "druh_vozidla":      druh,
                "kategorie_vozidla": d.get("Kategorie", ""),
                "cislo_schvaleni":   d.get("CisloTypovehoSchvaleni", ""),
            }
        status = resp.get("Status")
        if status == 3:
            return {"success": False, "error": "Vozidlo nenalezeno"}
        return {"success": False, "error": f"Chyba registru (status {status})"}
    except Exception:
        return {"success": False, "error": "Chyba spojení"}

@app.route("/api/orv", methods=["POST"])
def api_orv():
    body = request.json or {}
    return jsonify(lookup_orv(body.get("serie", ""), body.get("cislo", "")))

@app.route("/api/generate", methods=["POST"])
def api_generate():
    raw = request.json or {}
    # Sanitize: strip all string values
    data = {k: v.strip() if isinstance(v, str) else v for k, v in raw.items()}
    mode = data.get("mode", "prevod")

    out_dir = os.path.join(DATA_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    result = {"success": True}

    # Build ID overlays — right-aligned to x=554, y = bottom of name field + 3
    # zmeny.pdf: page0 původní(y=628), dos_prov(y=420); page1 nový(y=545), novy_prov(y=350)
    # zapis.pdf: page0 nový(y=683), prov(y=533)
    def _id_text(val):
        return f"ID: {val}" if val else None

    zmeny_overlays, zapis_overlays = [], []
    if _id_text(data.get("puvodni_id")):
        zmeny_overlays.append((0, 554, 628, _id_text(data["puvodni_id"])))
    if data.get("puvodni_prov_jiny") and _id_text(data.get("puvodni_prov_id")):
        zmeny_overlays.append((0, 554, 420, _id_text(data["puvodni_prov_id"])))
    elif not data.get("puvodni_prov_jiny") and _id_text(data.get("puvodni_id")):
        zmeny_overlays.append((0, 554, 420, _id_text(data["puvodni_id"])))
    if _id_text(data.get("novy_id")):
        zmeny_overlays.append((1, 554, 545, _id_text(data["novy_id"])))
        zapis_overlays.append((0, 554, 683, _id_text(data["novy_id"])))
    if data.get("novy_prov_jiny") and _id_text(data.get("novy_prov_id")):
        zmeny_overlays.append((1, 554, 350, _id_text(data["novy_prov_id"])))
        zapis_overlays.append((0, 554, 533, _id_text(data["novy_prov_id"])))
    elif not data.get("novy_prov_jiny") and _id_text(data.get("novy_id")):
        zmeny_overlays.append((1, 554, 350, _id_text(data["novy_id"])))
        zapis_overlays.append((0, 554, 533, _id_text(data["novy_id"])))

    if mode == "prevod":
        zmeny_bytes = fill_pdf(PDF_ZMENY, build_zmeny_fields(data))
        zapis_bytes = fill_pdf(PDF_ZAPIS, build_zapis_fields(data))
        if zmeny_overlays: zmeny_bytes = add_id_overlay(zmeny_bytes, zmeny_overlays)
        if zapis_overlays: zapis_bytes = add_id_overlay(zapis_bytes, zapis_overlays)
        fname_zmeny = os.path.join(out_dir, f"zmeny_{ts}.pdf")
        fname_zapis = os.path.join(out_dir, f"zapis_{ts}.pdf")
        with open(fname_zmeny, "wb") as f: f.write(zmeny_bytes)
        with open(fname_zapis, "wb") as f: f.write(zapis_bytes)
        result["zmeny"] = f"/download/zmeny_{ts}.pdf"
        result["zapis"] = f"/download/zapis_{ts}.pdf"
    else:  # zapis noveho vozidla
        zapis_bytes = fill_pdf(PDF_ZAPIS, build_zapis_fields(data))
        if zapis_overlays: zapis_bytes = add_id_overlay(zapis_bytes, zapis_overlays)
        fname_zapis = os.path.join(out_dir, f"zapis_{ts}.pdf")
        with open(fname_zapis, "wb") as f: f.write(zapis_bytes)
        result["zapis"] = f"/download/zapis_{ts}.pdf"

    # Attach plné moci for any party whose firm has one stored
    plne_moce = []
    for ico_key in ["puvodni_ico", "novy_ico", "puvodni_prov_ico", "novy_prov_ico"]:
        ico = "".join(c for c in str(data.get(ico_key, "")).strip() if c.isdigit())
        if ico:
            pm_path = os.path.join(PLNE_MOCE_DIR, f"{ico}.pdf")
            if os.path.exists(pm_path):
                url = f"/plna-moc/{ico}"
                if url not in plne_moce:
                    plne_moce.append(url)
    if plne_moce:
        result["plne_moce"] = plne_moce

    return jsonify(result)

@app.route("/api/scan", methods=["POST"])
def api_scan():
    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image provided"})
    f = request.files['image']
    mime_type = f.mimetype or "image/jpeg"
    model = request.form.get('model', 'sonnet')
    image_b64 = base64.b64encode(f.read()).decode('utf-8')
    result = scan_document(image_b64, mime_type, model)
    if not _has_data(result):
        result = scan_document(rotate_180(image_b64, mime_type), mime_type, model)
    return jsonify(result)

@app.route("/api/save-scan", methods=["POST"])
def api_save_scan():
    data = request.get_json()
    if not data or 'image' not in data:
        return jsonify({"success": False, "error": "No image data"})
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"scan_{ts}.jpg"
    filepath = os.path.join(SCANS_DIR, filename)
    img_data = data['image']
    if ',' in img_data:
        img_data = img_data.split(',', 1)[1]
    with open(filepath, 'wb') as f:
        f.write(base64.b64decode(img_data))
    return jsonify({"success": True, "filename": filename})

@app.route("/api/scan-all", methods=["POST"])
def api_scan_all():
    # Accept either saved filenames (JSON) or uploaded files (multipart)
    model = request.form.get('model', 'sonnet')
    filenames = request.form.getlist('filenames')
    content = []
    if filenames:
        for fname in filenames:
            safe = os.path.basename(fname)
            filepath = os.path.join(SCANS_DIR, safe)
            if not os.path.exists(filepath):
                continue
            with open(filepath, 'rb') as f:
                image_b64 = base64.b64encode(f.read()).decode('utf-8')
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    else:
        images = request.files.getlist('images')
        if not images:
            return jsonify({"success": False, "error": "No images provided"})
        for img in images:
            mime_type = img.mimetype or "image/jpeg"
            image_b64 = base64.b64encode(img.read()).decode('utf-8')
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}})
    if not content:
        return jsonify({"success": False, "error": "No valid images found"})
    content.append({"type": "text", "text": ORV_SCAN_PROMPT})
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODELS.get(model, MODELS["sonnet"]),
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": content}]
            },
            timeout=45
        )
        result = response.json()
        if "error" in result:
            return jsonify({"success": False, "error": result["error"].get("message", "API error")})
        text = result["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        return jsonify({"success": True, "data": json.loads(text.strip())})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/scan-orv", methods=["POST"])
def api_scan_orv():
    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image provided"})
    f = request.files['image']
    mime_type = f.mimetype or "image/jpeg"
    model = request.form.get('model', 'sonnet')
    image_b64 = base64.b64encode(f.read()).decode('utf-8')
    for candidate in [image_b64, rotate_180(image_b64, mime_type)]:
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODELS.get(model, MODELS["sonnet"]),
                    "max_tokens": 1200,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": candidate}},
                            {"type": "text", "text": ORV_SCAN_PROMPT}
                        ]
                    }]
                },
                timeout=30
            )
            result = response.json()
            if "error" in result:
                return jsonify({"success": False, "error": result["error"].get("message", "API error")})
            text = result["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"): text = text[4:]
            data = json.loads(text.strip())
            if data.get("spz") or data.get("vin") or data.get("znacka") or data.get("registracni_znacka") or (data.get("vlastnik") or {}).get("jmeno"):
                return jsonify({"success": True, "data": data})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": True, "data": data})

@app.route("/download/<filename>")
def download(filename):
    path = os.path.join(DATA_DIR, "output", filename)
    if not os.path.exists(path):
        return "File not found", 404
    return send_file(path, as_attachment=False, mimetype="application/pdf")

# ── Update endpoints ─────────────────────────────────────────────────────────
@app.route("/api/version")
def api_version():
    return jsonify({"version": __version__})

@app.route("/api/update-status")
def api_update_status():
    try:
        import updater
        return jsonify({
            "available": updater.update_ready,
            "version": updater.update_version,
            "current": __version__,
            "error": updater.update_error,
        })
    except Exception:
        return jsonify({"available": False, "version": None, "current": __version__})

@app.route("/api/apply-update", methods=["POST"])
def api_apply_update():
    try:
        import updater
        updater.apply_update_and_restart()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    app.run(debug=True, port=5050)
