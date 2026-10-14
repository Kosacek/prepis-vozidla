"""Náhledy stránek PDF jako PNG — pro sdílenou stránku /<kód>.

Proč obrázky a ne vložené PDF: v iframu Chrome ukazuje PDF stísněně a
rozbitě (viz CLAUDE.md, zkoušeno dvakrát) a Android Chrome vložené PDF
neukáže vůbec — stáhne ho. Obrázek stránky se ukáže všude stejně, takže
protějšek nejdřív VIDÍ, co tiskne, a teprve pak otevře samotné PDF.

Vyplněná textová pole kreslíme SAMI (Pillow + DejaVu Sans), ne PDFiem.
Naše PDF mají NeedAppearances=True — vzhled polí si vyrábí prohlížeč, a
PDFium to na Linuxu umí jen písmem Helvetica/WinAnsi: ě č ř ď ň ť z náhledu
mizely (2026-10-14, na Windows to přitom fungovalo, proto to unikalo).
PDFium proto kreslí stránku bez textových polí (formulář, zaškrtávátka) a
hodnoty polí se dopíšou na jejich místa — rozdělené po znacích u polí
„comb" (RZ, VIN, RČ, IČO), zarovnané podle /Q, velikost podle /DA.

Na NASu (ARM) trvá stránka zlomek sekundy; posledních pár náhledů drží
cache v paměti, ať se stránka při návratu nevykresluje znovu.
"""
from __future__ import annotations

import io
import logging
import os
import re
import threading
from functools import lru_cache

_log = logging.getLogger(__name__)

PISMO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts", "DejaVuSans.ttf")

_FF_VICERADKOVE = 1 << 12
_FF_COMB = 1 << 24

# 144 DPI: A4 vyjde ~1190 × 1680 px. Na počítači se stránka ukazuje na celou
# výšku okna (s Windows škálováním 125–150 % to je ~1300 px), při 100 DPI
# byl text rozmazaný.
MERITKO = 144 / 72
MAX_STRAN = 12  # víc stránek žádný z našich dokumentů nemá; brzda proti nesmyslům

# PDFium není vláknově bezpečné (gunicorn běží s vlákny i workery).
_zamek = threading.Lock()


def _klic(cesta: str) -> tuple[str, float]:
    return cesta, os.path.getmtime(cesta)


@lru_cache(maxsize=64)
def _pocet(cesta: str, _mtime: float) -> int:
    import pypdfium2 as pdfium
    with _zamek:
        pdf = pdfium.PdfDocument(cesta)
        try:
            return min(len(pdf), MAX_STRAN)
        finally:
            pdf.close()


def _textova_pole(stranka) -> list[dict]:
    """Vyplněná textová pole jedné stránky (pypdf): kde leží a co v nich je.
    /FT, /V, /DA … se dědí z rodiče, když widget sám nemá."""
    pole = []
    for a in stranka.get("/Annots") or []:
        w = a.get_object()
        if w.get("/Subtype") != "/Widget":
            continue
        rodic = w["/Parent"].get_object() if "/Parent" in w else {}

        def g(k, _w=w, _r=rodic):
            return _w.get(k, _r.get(k))

        hodnota = g("/V")
        if g("/FT") != "/Tx" or hodnota is None or not str(hodnota).strip():
            continue
        m = re.search(r"([\d.]+)\s+Tf", str(g("/DA") or ""))
        ff = int(g("/Ff") or 0)
        mk = w.get("/MK") or {}
        bc = [float(c) for c in (mk.get("/BC") or [])]
        bs = w.get("/BS") or {}
        pole.append({
            # Rámeček pole (/MK /BC) — kreslí ho prohlížeč spolu s textem.
            "ramecek": _seda(bc) if bc else None,
            "ramecek_sirka": float(bs.get("/W", 1)),
            "rect": [float(x) for x in w["/Rect"]],
            "text": str(hodnota),
            "velikost": float(m.group(1)) if m else 0.0,
            "comb": int(g("/MaxLen") or 0) if ff & _FF_COMB else 0,
            "viceradkove": bool(ff & _FF_VICERADKOVE),
            "q": int(g("/Q") or 0),
        })
    return pole


def _seda(barva: list[float]) -> int:
    """Barva PDF (šedá / RGB / CMYK) → odstín šedé 0–255."""
    if len(barva) == 1:
        return round(barva[0] * 255)
    if len(barva) == 3:
        return round((0.299 * barva[0] + 0.587 * barva[1] + 0.114 * barva[2]) * 255)
    c, m, y, k = (barva + [0, 0, 0, 0])[:4]
    return round((1 - min(1, 0.3 * c + 0.59 * m + 0.11 * y + k)) * 255)


def bez_textovych_poli(data: bytes, index: int) -> tuple[bytes, list[dict]]:
    """Kopie PDF, kde stránka `index` nemá textová pole, + seznam těch polí.
    Zaškrtávátka a ostatní anotace zůstanou — ty PDFium kreslí správně."""
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(io.BytesIO(data))
    stranka = r.pages[index]
    if int(stranka.get("/Rotate") or 0) % 360:
        return data, []  # otočené stránky naše tiskopisy nemají; ať je kreslí PDFium
    pole = _textova_pole(stranka)
    if not pole:
        return data, []
    # Souřadnice polí vztáhnout k ořezu stránky — to, co PDFium vykreslí.
    llx, lly = float(stranka.cropbox.left), float(stranka.cropbox.bottom)
    for p in pole:
        x0, y0, x1, y1 = p["rect"]
        p["rect"] = [x0 - llx, y0 - lly, x1 - llx, y1 - lly]
    w = PdfWriter(clone_from=r)
    cil = w.pages[index]
    zbyle = []
    for a in cil.get("/Annots") or []:
        o = a.get_object()
        rodic = o["/Parent"].get_object() if "/Parent" in o else {}
        if o.get("/Subtype") == "/Widget" and o.get("/FT", rodic.get("/FT")) == "/Tx":
            continue
        zbyle.append(a)
    from pypdf.generic import ArrayObject, NameObject
    cil[NameObject("/Annots")] = ArrayObject(zbyle)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue(), pole


def _pismo(velikost_px: float):
    from PIL import ImageFont
    return ImageFont.truetype(PISMO, max(1, round(velikost_px)))


def _dopis_pole(obrazek, pole: list[dict], vyska_pt: float, meritko: float) -> None:
    """Nakreslí hodnoty polí tam, kde by je nakreslil prohlížeč PDF."""
    from PIL import ImageDraw
    kresli = ImageDraw.Draw(obrazek)
    for p in pole:
        x0, y0, x1, y1 = p["rect"]
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        sirka, vyska = x1 - x0, y1 - y0
        if p["ramecek"] is not None and p["ramecek_sirka"] > 0:
            kresli.rectangle([x0 * meritko, (vyska_pt - y1) * meritko,
                              x1 * meritko, (vyska_pt - y0) * meritko],
                             outline=p["ramecek"], width=max(1, round(p["ramecek_sirka"] * meritko)))
        # Auto velikost (0 Tf) jako v prohlížečích: na výšku pole, max 12 b.
        vel = p["velikost"] or min(12.0, (vyska - 4) * 0.8)
        text = p["text"]
        if not p["comb"] and not p["viceradkove"]:
            while vel > 4 and _pismo(vel * meritko).getlength(text) / meritko > sirka - 4:
                if p["velikost"]:
                    break  # pevná velikost se nezmenšuje, jen přeteče (jako v Chrome)
                vel -= 0.5
        pismo = _pismo(vel * meritko)
        stred_y = (vyska_pt - (y0 + y1) / 2) * meritko

        if p["comb"]:
            bunka = sirka / p["comb"]
            for i, znak in enumerate(text[:p["comb"]]):
                cx = (x0 + bunka * (i + 0.5)) * meritko
                kresli.text((cx, stred_y), znak, font=pismo, fill=0, anchor="mm")
        elif p["viceradkove"]:
            y = (vyska_pt - y1 + 2) * meritko
            for radek in text.splitlines() or [text]:
                kresli.text(((x0 + 2) * meritko, y), radek, font=pismo, fill=0, anchor="la")
                y += vel * 1.15 * meritko
        else:
            if p["q"] == 1:
                xy, kotva = ((x0 + x1) / 2 * meritko, stred_y), "mm"
            elif p["q"] == 2:
                xy, kotva = ((x1 - 2) * meritko, stred_y), "rm"
            else:
                xy, kotva = ((x0 + 2) * meritko, stred_y), "lm"
            kresli.text(xy, text, font=pismo, fill=0, anchor=kotva)


@lru_cache(maxsize=32)
def _png(cesta: str, _mtime: float, strana: int) -> bytes:
    import pypdfium2 as pdfium
    with open(cesta, "rb") as f:
        data = f.read()
    try:
        data, pole = bez_textovych_poli(data, strana - 1)
    except Exception as e:  # neobvyklé PDF — radši náhled od PDFia než žádný
        _log.warning("náhled: pole nejde přečíst %s: %s", os.path.basename(cesta), e)
        pole = []
    with _zamek:
        pdf = pdfium.PdfDocument(data)
        try:
            pdf.init_forms()
            stranka = pdf[strana - 1]
            vyska_pt = stranka.get_height()
            obrazek = stranka.render(scale=MERITKO, may_draw_forms=True).to_pil()
        finally:
            pdf.close()
    obrazek = obrazek.convert("L")
    _dopis_pole(obrazek, pole, vyska_pt, MERITKO)
    buf = io.BytesIO()
    obrazek.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def pocet_stran(cesta: str) -> int:
    """Kolik stran má smysl ukázat; 0 = náhled nejde (rozbité PDF, chyba)."""
    try:
        return _pocet(*_klic(cesta))
    except Exception as e:
        _log.warning("náhled: nejde otevřít %s: %s", os.path.basename(cesta), e)
        return 0


def stranka_png(cesta: str, strana: int) -> bytes | None:
    """PNG jedné stránky (číslováno od 1), nebo None když taková není."""
    if not 1 <= strana <= pocet_stran(cesta):
        return None
    try:
        return _png(*_klic(cesta), strana)
    except Exception as e:
        _log.warning("náhled: nejde vykreslit %s/%d: %s", os.path.basename(cesta), strana, e)
        return None
